from __future__ import annotations

from datetime import timedelta
import hashlib

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    JournalEntry, JournalLine, LedgerAccount, SettlementBatch, SettlementLine,
    Shipment, ShippingQuote, Vendor, VendorOrder, VendorProduct,
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
    # Seller identity is snapshotted on each order line. Never infer a seller
    # from product_id alone: multiple vendors may list the same catalog product.
    if any(not item.vendor_listing_id for item in items):
        # Deliberately avoid partial seller routing for a mixed/legacy order.
        return []
    grouped = {}
    for item in items:
        listing = item.vendor_listing
        if (
            listing.status != VendorProduct.Status.ACTIVE
            or listing.vendor.status != Vendor.Status.ACTIVE
            or not listing.vendor.user.is_active
        ):
            raise ValidationError("یکی از فروشندگان سفارش در زمان تسویه سفارش فعال نیست.")
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
        journal_lines = [{"account": clearing, "debit": int(order.total_amount), "credit": 0, "memo": order.number}]
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


def address_fingerprint(*, user, address) -> str:
    raw = "|".join([
        str(user.pk), str(address.pk), str(address.postal_code or ""),
        str(address.city_id), str(address.description or ""), str(address.title or ""),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_shipping_quote(*, user, cart_item, address, provider):
    """Quote one seller parcel using seller-configured origin and customer address."""
    from .carriers import get_carrier
    from django.utils import timezone

    listing = cart_item.vendor_listing
    if not listing:
        raise ValidationError("این قلم سبد به فروشنده مشخصی متصل نیست.")
    if cart_item.cart.user_id != user.pk:
        raise ValidationError("این قلم سبد متعلق به کاربر فعلی نیست.")
    if address.user_id != user.pk:
        raise ValidationError("آدرس انتخاب‌شده متعلق به کاربر فعلی نیست.")
    if listing.status != VendorProduct.Status.ACTIVE or not listing.vendor.can_receive_orders:
        raise ValidationError("این فروشنده در حال حاضر سفارش نمی‌پذیرد.")
    if not listing.vendor.pickup_postal_code:
        raise ValidationError("فروشنده هنوز کد پستی مبدأ ارسال را در پنل تکمیل نکرده است.")
    if not listing.weight_grams:
        raise ValidationError("وزن بسته‌بندی‌شده محصول باید توسط فروشنده ثبت شود.")
    if not all((listing.package_length_cm, listing.package_width_cm, listing.package_height_cm)):
        raise ValidationError("ابعاد بسته‌بندی محصول باید توسط فروشنده تکمیل شود.")
    provider = str(provider).lower()
    if provider not in {"tipax", "post"}:
        raise ValidationError("شرکت حمل‌ونقل انتخاب‌شده پشتیبانی نمی‌شود.")
    payload = {
        "origin_postal_code": listing.vendor.pickup_postal_code,
        "destination_postal_code": address.postal_code,
        "weight_grams": listing.weight_grams * cart_item.quantity,
        "length_cm": listing.package_length_cm,
        "width_cm": listing.package_width_cm,
        "height_cm": listing.package_height_cm,
        "declared_value": int(listing.retail_price) * cart_item.quantity,
        "service_level": "standard",
        "quantity": cart_item.quantity,
    }
    quote = get_carrier(provider).quote(payload)
    expires_at = None
    if quote.expires_at:
        from django.utils.dateparse import parse_datetime
        expires_at = parse_datetime(str(quote.expires_at))
        if expires_at and timezone.is_naive(expires_at):
            expires_at = timezone.make_aware(expires_at, timezone.get_current_timezone())
    expires_at = expires_at or (timezone.now() + timedelta(minutes=15))
    if expires_at <= timezone.now():
        raise ValidationError("شرکت حمل‌ونقل هزینه‌ای با مهلت اعتبار گذشته برگردانده است.")
    return ShippingQuote.objects.create(
        user=user,
        cart_item=cart_item,
        vendor_listing=listing,
        provider=provider,
        amount=quote.amount,
        currency=quote.currency,
        quote_reference=quote.reference,
        quantity=cart_item.quantity,
        address_fingerprint=address_fingerprint(user=user, address=address),
        expires_at=expires_at,
        provider_payload={"request": payload, "response": quote.raw or {}},
    )


def consume_shipping_quotes(*, user, cart, address, items, quote_ids, now=None):
    """Validate and consume the exact current quote set atomically for checkout."""
    from django.utils import timezone

    now = now or timezone.now()
    seller_items = [item for item in items if item.vendor_listing_id]
    if not seller_items:
        if quote_ids:
            raise ValidationError("برای سبدی بدون فروشنده، استعلام حمل نامعتبر است.")
        return 0
    if len(seller_items) != len(items):
        raise ValidationError("برای سفارش چندفروشندگی، همه اقلام باید فروشنده مشخص داشته باشند.")
    normalized_ids = [str(value).strip() for value in quote_ids if str(value).strip()]
    if len(normalized_ids) != len(seller_items) or len(set(normalized_ids)) != len(normalized_ids):
        raise ValidationError("برای هر قلم فروشنده باید یک هزینه ارسال معتبر انتخاب شود.")
    quotes = list(
        ShippingQuote.objects.select_for_update().filter(
            uuid__in=normalized_ids,
            user=user,
            cart_item__cart=cart,
            status=ShippingQuote.Status.VALID,
            expires_at__gt=now,
        )
    )
    if len(quotes) != len(seller_items):
        raise ValidationError("یکی از استعلام‌های ارسال منقضی یا نامعتبر است؛ هزینه ارسال را دوباره محاسبه کنید.")
    by_item = {quote.cart_item_id: quote for quote in quotes}
    fingerprint = address_fingerprint(user=user, address=address)
    total = 0
    for item in seller_items:
        quote = by_item.get(item.id)
        if (
            not quote
            or quote.vendor_listing_id != item.vendor_listing_id
            or quote.quantity != item.quantity
            or quote.address_fingerprint != fingerprint
        ):
            raise ValidationError("استعلام ارسال با آدرس، فروشنده یا تعداد فعلی سبد مطابقت ندارد.")
        total += quote.amount
    ShippingQuote.objects.filter(id__in=[quote.id for quote in quotes]).update(
        status=ShippingQuote.Status.CONSUMED,
        used_at=now,
    )
    return total
