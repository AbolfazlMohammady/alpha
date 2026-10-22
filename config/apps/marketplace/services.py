from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    JournalEntry, JournalLine, LedgerAccount, SettlementBatch, SettlementLine,
    Shipment, Vendor, VendorOrder, VendorProduct,
)


def get_system_account(code: str, name: str, kind: str, currency: str = "IRT") -> LedgerAccount:
    account, _ = LedgerAccount.objects.get_or_create(
        code=code,
        defaults={"name": name, "kind": kind, "currency": currency},
    )
    if account.kind != kind or account.currency != currency:
        raise ValidationError(f"حساب مالی {code} با تنظیمات ناسازگار از قبل وجود دارد.")
    return account


def post_journal(*, idempotency_key, kind, description, lines, order=None, vendor_order=None, created_by=None, metadata=None):
    """Create an immutable, balanced double-entry journal exactly once.

    Each line is {account: LedgerAccount, debit: int, credit: int, memo?: str}.
    All values use the project's integer IRT convention; never use floats.
    """
    normalized = []
    debit_total = credit_total = 0
    for item in lines:
        debit, credit = int(item.get("debit", 0)), int(item.get("credit", 0))
        if debit < 0 or credit < 0 or (debit == 0) == (credit == 0):
            raise ValidationError("هر ردیف سند باید دقیقاً یک مبلغ بدهکار یا بستانکار مثبت داشته باشد.")
        account = item["account"]
        if not account.is_active:
            raise ValidationError(f"حساب {account.code} غیرفعال است.")
        if account.currency != "IRT":
            raise ValidationError("تبدیل ارز در این نسخه پشتیبانی نمی‌شود.")
        normalized.append((account, debit, credit, item.get("memo", "")))
        debit_total += debit
        credit_total += credit
    if len(normalized) < 2 or debit_total != credit_total:
        raise ValidationError(f"سند نامتوازن است: بدهکار {debit_total}، بستانکار {credit_total}.")

    with transaction.atomic():
        existing = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if existing.status not in {JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED}:
                raise ValidationError("کلید تکراری به سند ناقص متصل است؛ بررسی مدیریتی لازم است.")
            return existing, False
        try:
            entry = JournalEntry.objects.create(
                idempotency_key=idempotency_key,
                kind=kind,
                description=description,
                order=order,
                vendor_order=vendor_order,
                created_by=created_by,
                metadata=metadata or {},
            )
            JournalLine.objects.bulk_create([
                JournalLine(entry=entry, account=account, debit=debit, credit=credit, memo=memo)
                for account, debit, credit, memo in normalized
            ])
            entry.status = JournalEntry.Status.POSTED
            entry.posted_at = timezone.now()
            entry.save(update_fields=("status", "posted_at"))
            return entry, True
        except IntegrityError:
            existing = JournalEntry.objects.get(idempotency_key=idempotency_key)
            return existing, False


def reverse_journal(*, entry: JournalEntry, idempotency_key: str, reason: str, created_by=None):
    """Reverse a posted journal with a new balanced journal; never edit history."""
    entry = JournalEntry.objects.prefetch_related("lines__account").get(pk=entry.pk)
    if entry.status == JournalEntry.Status.REVERSED:
        reversal = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
        if reversal:
            return reversal, False
        raise ValidationError("این سند قبلاً معکوس شده است.")
    if entry.status != JournalEntry.Status.POSTED:
        raise ValidationError("فقط سند قطعی را می‌توان معکوس کرد.")
    lines = [
        {
            "account": line.account,
            "debit": line.credit,
            "credit": line.debit,
            "memo": f"معکوس سند {entry.id}",
        }
        for line in entry.lines.all()
    ]
    with transaction.atomic():
        reversal, created = post_journal(
            idempotency_key=idempotency_key,
            kind="reversal",
            description=f"معکوس سند {entry.id}: {reason[:350]}",
            lines=lines,
            order=entry.order,
            vendor_order=entry.vendor_order,
            created_by=created_by,
            metadata={"reverses_entry_id": entry.id, "reason": reason},
        )
        if created:
            JournalEntry.objects.filter(pk=entry.pk, status=JournalEntry.Status.POSTED).update(status=JournalEntry.Status.REVERSED)
        return reversal, created


def create_vendor_orders_for_paid_order(order):
    """Split a paid order only when every item has an approved seller listing.

    Legacy single-store orders remain untouched until their products are assigned
    to vendors. This prevents silently losing an item from seller fulfilment.
    """
    from apps.orders.models import Order

    order = Order.objects.select_related("user").prefetch_related("items__product").get(pk=order.pk)
    if order.payment_status != Order.PaymentStatus.PAID:
        raise ValidationError("تفکیک سفارش فقط پس از پرداخت موفق مجاز است.")
    items = list(order.items.all())
    if not items:
        return []
    listings = {
        listing.product_id: listing
        for listing in VendorProduct.objects.select_related("vendor").filter(
            product_id__in=[item.product_id for item in items],
            status=VendorProduct.Status.ACTIVE,
            vendor__status=Vendor.Status.ACTIVE,
            vendor__user__is_active=True,
        )
    }
    if len(listings) != len({item.product_id for item in items}):
        # Deliberately avoid partial seller routing for a mixed/legacy order.
        return []
    grouped = {}
    for item in items:
        listing = listings[item.product_id]
        grouped.setdefault(listing.vendor_id, {"vendor": listing.vendor, "items": [], "subtotal": 0})
        gross = int(item.line_total)
        grouped[listing.vendor_id]["subtotal"] += gross
        grouped[listing.vendor_id]["items"].append({
            "order_item_id": item.id,
            "product_id": item.product_id,
            "product_name": item.product_name,
            "variant_sku": item.variant_sku,
            "color_name": item.color_name,
            "size_name": item.size_name,
            "quantity": item.quantity,
            "unit_price": int(item.unit_price),
            "line_total": gross,
            "vendor_product_id": listing.id,
            "custom_design_code": item.custom_design_code,
            "custom_design_snapshot": item.custom_design_snapshot,
        })

    gross_sum = sum(group["subtotal"] for group in grouped.values())
    discount_remaining = int(order.discount_amount or 0)
    lines = []
    created_orders = []
    with transaction.atomic():
        for vendor_id, group in grouped.items():
            vendor = group["vendor"]
            # Allocate order-level discount proportionally, with the final seller
            # absorbing any integer remainder so allocations exactly reconcile.
            if vendor_id == list(grouped.keys())[-1]:
                discount = discount_remaining
            else:
                discount = (int(order.discount_amount or 0) * group["subtotal"] // max(gross_sum, 1))
                discount_remaining -= discount
            net_sales = max(group["subtotal"] - discount, 0)
            commission = (net_sales * vendor.commission_bps + 5000) // 10000
            commission = min(commission, net_sales)
            payable = net_sales - commission
            vendor_order, _ = VendorOrder.objects.get_or_create(
                order=order,
                vendor=vendor,
                defaults={
                    "items_snapshot": group["items"],
                    "subtotal": net_sales,
                    "commission_amount": commission,
                    "vendor_payable": payable,
                    "currency": order.currency,
                },
            )
            created_orders.append(vendor_order)
            lines.append((vendor, vendor_order, net_sales, commission, payable))

        # Posting is idempotent and happens once per successfully paid order.
        clearing = get_system_account("gateway_clearing", "وجوه دریافتی درگاه", LedgerAccount.Kind.ASSET, order.currency)
        commission_account = get_system_account("platform_commission", "درآمد کمیسیون پلتفرم", LedgerAccount.Kind.REVENUE, order.currency)
        shipping_account = get_system_account("shipping_funds_payable", "وجوه تخصیص‌یافته به حمل", LedgerAccount.Kind.LIABILITY, order.currency)
        discount_account = get_system_account("sales_discounts", "تخفیف‌های فروش", LedgerAccount.Kind.EXPENSE, order.currency)
        journal_lines = [{"account": clearing, "debit": int(order.total_amount), "credit": 0, "memo": order.number}]
        if order.discount_amount:
            journal_lines.append({"account": discount_account, "debit": int(order.discount_amount), "credit": 0, "memo": order.number})
        for vendor, vendor_order, net_sales, commission, payable in lines:
            payable_account = get_system_account(
                f"vendor_payable_{vendor.id}",
                f"بستانکاری فروشنده: {vendor.store_name}",
                LedgerAccount.Kind.LIABILITY,
                order.currency,
            )
            if payable:
                journal_lines.append({"account": payable_account, "debit": 0, "credit": payable, "memo": order.number})
            if commission:
                journal_lines.append({"account": commission_account, "debit": 0, "credit": commission, "memo": order.number})
        if order.shipping_amount:
            journal_lines.append({"account": shipping_account, "debit": 0, "credit": int(order.shipping_amount), "memo": order.number})
        # A legacy checkout may not yet allocate shipping; only post when the
        # order's actual money components reconcile to its payable total.
        expected_credit = sum(line["credit"] for line in journal_lines)
        expected_debit = sum(line["debit"] for line in journal_lines)
        if expected_credit != expected_debit:
            raise ValidationError(
                "تفکیک مالی سفارش با تخفیف/هزینه ارسال فعلی سازگار نیست؛ قبل از ثبت سند، تخصیص مبالغ سفارش باید تکمیل شود."
            )
        post_journal(
            idempotency_key=f"order-paid:{order.uuid}",
            kind="order_payment",
            description=f"ثبت فروش و بدهی فروشندگان برای سفارش {order.number}",
            lines=journal_lines,
            order=order,
            metadata={"vendor_order_ids": [row.id for row in created_orders]},
        )
    return created_orders


def mark_vendor_order_delivered(vendor_order: VendorOrder, *, delivered_at=None):
    delivered_at = delivered_at or timezone.now()
    with transaction.atomic():
        locked = VendorOrder.objects.select_for_update().select_related("vendor").get(pk=vendor_order.pk)
        if locked.status == VendorOrder.Status.CANCELLED:
            raise ValidationError("سفارش لغوشده را نمی‌توان تحویل‌شده ثبت کرد.")
        if locked.status == VendorOrder.Status.DELIVERED:
            return locked, False
        locked.status = VendorOrder.Status.DELIVERED
        locked.delivered_at = delivered_at
        locked.settlement_eligible_at = delivered_at + timedelta(hours=locked.vendor.settlement_hold_hours)
        locked.save(update_fields=("status", "delivered_at", "settlement_eligible_at", "updated_at"))
        return locked, True


def create_daily_settlement_batches(*, now=None):
    """Create one approval batch per vendor for delivered, matured, unpaid orders."""
    now = now or timezone.now()
    created = []
    vendors = Vendor.objects.filter(status=Vendor.Status.ACTIVE).order_by("id")
    for vendor in vendors:
        eligible = list(
            VendorOrder.objects.filter(
                vendor=vendor,
                status=VendorOrder.Status.DELIVERED,
                settlement_eligible_at__lte=now,
            )
            .exclude(settlement_lines__batch__status__in=[
                SettlementBatch.Status.PENDING_APPROVAL,
                SettlementBatch.Status.APPROVED,
                SettlementBatch.Status.PROCESSING,
                SettlementBatch.Status.PAID,
            ])
            .distinct()
            .order_by("id")
        )
        if not eligible:
            continue
        key = f"daily-settlement:{vendor.id}:{now.date().isoformat()}"
        with transaction.atomic():
            batch, was_created = SettlementBatch.objects.get_or_create(
                idempotency_key=key,
                defaults={
                    "vendor": vendor,
                    "status": SettlementBatch.Status.PENDING_APPROVAL,
                    "period_start": now.replace(hour=0, minute=0, second=0, microsecond=0),
                    "period_end": now,
                    "gross_amount": sum(item.subtotal for item in eligible),
                    "commission_amount": sum(item.commission_amount for item in eligible),
                    "payable_amount": sum(item.vendor_payable for item in eligible),
                    "order_ids": [item.order_id for item in eligible],
                },
            )
            if was_created:
                SettlementLine.objects.bulk_create([
                    SettlementLine(
                        batch=batch,
                        vendor_order=item,
                        gross_amount=item.subtotal,
                        commission_amount=item.commission_amount,
                        payable_amount=item.vendor_payable,
                    )
                    for item in eligible
                ])
                created.append(batch)
    return created


def approve_settlement(*, batch_id, approver):
    if not approver or not approver.is_authenticated or not (approver.is_staff or approver.is_superuser):
        raise PermissionDenied("تأیید تسویه فقط برای مدیر مجاز است.")
    with transaction.atomic():
        batch = SettlementBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status != SettlementBatch.Status.PENDING_APPROVAL:
            raise ValidationError("فقط تسویه در انتظار تأیید را می‌توان تأیید کرد.")
        if not batch.vendor.can_receive_orders:
            raise ValidationError("وضعیت فروشنده اجازه تسویه نمی‌دهد.")
        if not batch.vendor.bank_details_verified_at or not batch.vendor.bank_iban:
            raise ValidationError("اطلاعات بانکی فروشنده هنوز تأیید نشده است.")
        if batch.payable_amount <= 0:
            raise ValidationError("مبلغ تسویه باید مثبت باشد.")
        batch.status = SettlementBatch.Status.APPROVED
        batch.approved_by = approver
        batch.approved_at = timezone.now()
        batch.save(update_fields=("status", "approved_by", "approved_at"))
        return batch


def record_payout_result(*, batch_id, provider_reference, succeeded, failure_reason=""):
    """Record a confirmed external payout result; this does not initiate a bank transfer."""
    with transaction.atomic():
        batch = SettlementBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status not in {SettlementBatch.Status.APPROVED, SettlementBatch.Status.PROCESSING, SettlementBatch.Status.FAILED}:
            raise ValidationError("وضعیت تسویه برای ثبت نتیجه پرداخت معتبر نیست.")
        if succeeded:
            if not provider_reference:
                raise ValidationError("شناسه مرجع پرداخت موفق الزامی است.")
            batch.status = SettlementBatch.Status.PAID
            batch.payout_reference = provider_reference[:180]
            batch.paid_at = timezone.now()
            batch.failure_reason = ""
        else:
            batch.status = SettlementBatch.Status.FAILED
            batch.failure_reason = (failure_reason or "پرداخت ناموفق بود.")[:4000]
        batch.save(update_fields=("status", "payout_reference", "paid_at", "failure_reason"))
        return batch
