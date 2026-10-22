from __future__ import annotations

from datetime import timedelta
import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    JournalEntry, JournalLine, LedgerAccount, SettlementBatch, SettlementLine,
    FinancialReconciliation, Shipment, ShippingQuote, Vendor, VendorOrder, VendorProduct,
)


def get_system_account(code: str, name: str, kind: str, currency: str = "IRT", vendor=None) -> LedgerAccount:
    account, _ = LedgerAccount.objects.get_or_create(
        code=code,
        defaults={"name": name, "kind": kind, "currency": currency, "vendor": vendor},
    )
    expected_vendor_id = vendor.pk if vendor else None
    if account.kind != kind or account.currency != currency or account.vendor_id != expected_vendor_id:
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

    fingerprint_payload = [
        {"account_id": account.pk, "debit": debit, "credit": credit, "currency": account.currency, "memo": memo}
        for account, debit, credit, memo in normalized
    ]
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    with transaction.atomic():
        existing = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if existing.status not in {JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED}:
                raise ValidationError("کلید تکراری به سند ناقص متصل است؛ بررسی مدیریتی لازم است.")
            if existing.metadata.get("_posting_fingerprint") != fingerprint:
                raise ValidationError("کلید idempotency قبلاً با مبالغ متفاوت استفاده شده است؛ ثبت جدید متوقف شد.")
            return existing, False
        try:
            entry = JournalEntry.objects.create(
                idempotency_key=idempotency_key,
                kind=kind,
                description=description,
                order=order,
                vendor_order=vendor_order,
                created_by=created_by,
                metadata={**(metadata or {}), "_posting_fingerprint": fingerprint},
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
            shipping_share = ShippingQuote.objects.filter(
                order=order,
                vendor_listing__vendor=vendor,
            ).aggregate(total=Sum("amount"))["total"] or 0
            vendor_order, _ = VendorOrder.objects.get_or_create(
                order=order,
                vendor=vendor,
                defaults={
                    "items_snapshot": group["items"],
                    "subtotal": net_sales,
                    "customer_shipping_amount": int(shipping_share),
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
                vendor=vendor,
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
        if locked.status == VendorOrder.Status.DISPUTED:
            raise ValidationError("سفارش دارای اختلاف را نمی‌توان بدون رفع اختلاف تحویل‌شده ثبت کرد.")
        if locked.status == VendorOrder.Status.DELIVERED and locked.delivered_at and delivered_at <= locked.delivered_at:
            return locked, False
        locked.status = VendorOrder.Status.DELIVERED
        locked.delivered_at = delivered_at
        # When an order is split into several parcels, each later delivery
        # restarts the hold period so settlement waits after the final parcel.
        locked.settlement_eligible_at = delivered_at + timedelta(hours=locked.vendor.settlement_hold_hours)
        locked.save(update_fields=("status", "delivered_at", "settlement_eligible_at", "updated_at"))
        return locked, True


def create_daily_settlement_batches(*, now=None):
    """Create one approval batch per vendor for delivered, matured, unpaid orders."""
    now = now or timezone.now()
    created = []
    vendors = Vendor.objects.filter(status=Vendor.Status.ACTIVE).order_by("id")
    for vendor in vendors:
        candidates = list(
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
            .prefetch_related("shipments")
            .order_by("id")
        )
        eligible = []
        for candidate in candidates:
            shipments = list(candidate.shipments.all())
            # Do not settle before carrier delivery or while centrally-paid
            # shipment costs are unknown.
            if not shipments or any(shipment.status != Shipment.Status.DELIVERED for shipment in shipments):
                continue
            if any(
                shipment.payer == Shipment.Payer.PLATFORM and shipment.actual_cost is None
                for shipment in shipments
            ):
                continue
            eligible.append(candidate)
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
    """Record a confirmed external payout result and post the payout ledger entry."""
    with transaction.atomic():
        batch = SettlementBatch.objects.select_for_update().select_related("vendor").get(pk=batch_id)
        reference = str(provider_reference or "").strip()[:180]
        if batch.status == SettlementBatch.Status.PAID:
            if succeeded and reference and reference == batch.payout_reference:
                return batch
            raise ValidationError("تسویه پرداخت‌شده است و نتیجه جدید با سابقه آن سازگار نیست.")
        if batch.status not in {SettlementBatch.Status.APPROVED, SettlementBatch.Status.PROCESSING, SettlementBatch.Status.FAILED}:
            raise ValidationError("وضعیت تسویه برای ثبت نتیجه پرداخت معتبر نیست.")
        if succeeded:
            if not reference:
                raise ValidationError("شناسه مرجع پرداخت موفق الزامی است.")
            if SettlementBatch.objects.filter(payout_reference=reference, status=SettlementBatch.Status.PAID).exclude(pk=batch.pk).exists():
                raise ValidationError("این شناسه مرجع قبلاً برای تسویه دیگری ثبت شده است.")
            payable_account = get_system_account(
                f"vendor_payable_{batch.vendor_id}",
                f"بستانکاری فروشنده: {batch.vendor.store_name}",
                LedgerAccount.Kind.LIABILITY,
                batch.currency,
                vendor=batch.vendor,
            )
            clearing = get_system_account("platform_bank", "حساب بانکی پلتفرم", LedgerAccount.Kind.ASSET, batch.currency)
            post_journal(
                idempotency_key=f"vendor-payout:{batch.uuid}",
                kind="vendor_payout",
                description=f"واریز سهم فروشنده {batch.vendor.store_name} برای تسویه {batch.uuid}",
                lines=[
                    {"account": payable_account, "debit": batch.payable_amount, "credit": 0, "memo": reference},
                    {"account": clearing, "debit": 0, "credit": batch.payable_amount, "memo": reference},
                ],
                metadata={"settlement_batch_id": batch.id, "payout_reference": reference},
            )
            batch.status = SettlementBatch.Status.PAID
            batch.payout_reference = reference
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


def _vendor_group_quote_payload(*, items, vendor, address, user, lock_listings=False):
    """Build a deterministic shipping snapshot for all cart lines from one seller."""
    items = sorted(items, key=lambda item: item.id)
    listing_ids = sorted({item.vendor_listing_id for item in items if item.vendor_listing_id})
    listings_qs = VendorProduct.objects.filter(pk__in=listing_ids).select_related("vendor")
    if lock_listings:
        listings_qs = listings_qs.select_for_update()
    listings = {listing.pk: listing for listing in listings_qs}
    if len(listings) != len(listing_ids):
        raise ValidationError("یکی از محصولات فروشنده دیگر در دسترس نیست.")
    quantity_by_listing = {}
    stock_by_listing = {}
    for item in items:
        stock_by_listing[item.vendor_listing_id] = stock_by_listing.get(item.vendor_listing_id, 0) + int(item.quantity)
        if not item.custom_design_id:
            quantity_by_listing[item.vendor_listing_id] = quantity_by_listing.get(item.vendor_listing_id, 0) + int(item.quantity)
    snapshot = []
    total_weight = total_quantity = declared_value = 0
    length_cm = width_cm = height_cm = 0
    for item in items:
        listing = listings.get(item.vendor_listing_id)
        if not listing or listing.vendor_id != vendor.pk:
            raise ValidationError("همه اقلام استعلام باید متعلق به یک فروشنده باشند.")
        if listing.status != VendorProduct.Status.ACTIVE or not listing.vendor.can_receive_orders:
            raise ValidationError("یکی از محصولات این فروشنده دیگر سفارش نمی‌پذیرد.")
        if not listing.weight_grams or not all((listing.package_length_cm, listing.package_width_cm, listing.package_height_cm)):
            raise ValidationError("وزن و ابعاد بسته‌بندی همه محصولات باید تکمیل شده باشد.")
        if item.custom_design_id and (
            not listing.supports_custom_printing or not listing.vendor.supports_custom_printing
        ):
            raise ValidationError("این فروشنده امکان چاپ سفارشی این محصول را ندارد.")
        if item.custom_design_id:
            unit_price = int(item.custom_design.total_price)
        else:
            unit_price = int(listing.retail_price)
            if listing.wholesale_enabled:
                tier = listing.wholesale_tiers.filter(minimum_quantity__lte=quantity_by_listing.get(listing.pk, 0)).order_by("-minimum_quantity").first()
                if tier:
                    unit_price = int(tier.unit_price)
        quantity = int(item.quantity)
        total_quantity += quantity
        total_weight += int(listing.weight_grams) * quantity
        declared_value += unit_price * quantity
        length_cm = max(length_cm, int(listing.package_length_cm))
        width_cm = max(width_cm, int(listing.package_width_cm))
        height_cm += int(listing.package_height_cm) * quantity
        snapshot.append({
            "cart_item_id": item.id,
            "listing_id": listing.pk,
            "quantity": quantity,
            "unit_price": unit_price,
            "weight_grams": listing.weight_grams,
            "length_cm": listing.package_length_cm,
            "width_cm": listing.package_width_cm,
            "height_cm": listing.package_height_cm,
            "custom_design_id": str(item.custom_design_id or ""),
        })
    for listing_id, requested in stock_by_listing.items():
        if listings[listing_id].stock_quantity < requested:
            raise ValidationError("موجودی یکی از محصولات برای تعداد انتخاب‌شده کافی نیست.")
    fingerprint = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload = {
        "origin_postal_code": vendor.pickup_postal_code,
        "destination_postal_code": address.postal_code,
        "weight_grams": total_weight,
        "length_cm": length_cm,
        "width_cm": width_cm,
        "height_cm": height_cm,
        "declared_value": declared_value,
        "service_level": "standard",
        "quantity": total_quantity,
        "vendor_id": vendor.pk,
        "cart_item_ids": [item.id for item in items],
        "listing_ids": listing_ids,
        "cart_items_fingerprint": fingerprint,
    }
    return payload, fingerprint, listings


def create_shipping_quote(*, user, cart_item, address, provider):
    """Quote one combined parcel for all current cart lines belonging to a seller."""
    from .carriers import get_carrier
    from django.utils import timezone

    if not cart_item.vendor_listing_id:
        raise ValidationError("این قلم سبد به فروشنده مشخصی متصل نیست.")
    if cart_item.cart.user_id != user.pk:
        raise ValidationError("این قلم سبد متعلق به کاربر فعلی نیست.")
    if address.user_id != user.pk:
        raise ValidationError("آدرس انتخاب‌شده متعلق به کاربر فعلی نیست.")
    vendor = cart_item.vendor_listing.vendor
    if not vendor.pickup_postal_code:
        raise ValidationError("فروشنده هنوز کد پستی مبدأ ارسال را در پنل تکمیل نکرده است.")
    provider = str(provider).lower()
    if provider not in {"tipax", "post"}:
        raise ValidationError("شرکت حمل‌ونقل انتخاب‌شده پشتیبانی نمی‌شود.")
    items = list(
        cart_item.cart.items.filter(vendor_listing__vendor=vendor)
        .select_related("vendor_listing__vendor", "custom_design")
        .order_by("id")
    )
    if not items or cart_item.id not in {item.id for item in items}:
        raise ValidationError("اقلام سبد فروشنده پیدا نشد.")
    payload, group_fingerprint, _listings = _vendor_group_quote_payload(
        items=items, vendor=vendor, address=address, user=user,
    )
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
        vendor_listing=cart_item.vendor_listing,
        provider=provider,
        amount=quote.amount,
        currency=quote.currency,
        quote_reference=quote.reference,
        quantity=payload["quantity"],
        address_fingerprint=address_fingerprint(user=user, address=address),
        expires_at=expires_at,
        provider_payload={"request": payload, "group_fingerprint": group_fingerprint, "response": quote.raw or {}},
    )


def consume_shipping_quotes(*, user, cart, address, items, quote_ids, now=None):
    """Validate one current, seller-group shipping quote per seller atomically."""
    from django.utils import timezone

    now = now or timezone.now()
    seller_items = [item for item in items if item.vendor_listing_id]
    if not seller_items:
        if quote_ids:
            raise ValidationError("برای سبدی بدون فروشنده، استعلام حمل نامعتبر است.")
        return 0, []
    if len(seller_items) != len(items):
        raise ValidationError("برای سفارش چندفروشندگی، همه اقلام باید فروشنده مشخص داشته باشند.")
    normalized_ids = [str(value).strip() for value in quote_ids if str(value).strip()]
    listing_map = {
        listing.pk: listing
        for listing in VendorProduct.objects.select_for_update().filter(
            pk__in={item.vendor_listing_id for item in seller_items}
        ).select_related("vendor")
    }
    grouped = {}
    for item in seller_items:
        listing = listing_map.get(item.vendor_listing_id)
        if not listing:
            raise ValidationError("یکی از محصولات فروشنده دیگر پیدا نشد.")
        grouped.setdefault(listing.vendor_id, []).append(item)
    if len(normalized_ids) != len(set(normalized_ids)) or len(normalized_ids) != len(grouped):
        raise ValidationError("برای هر فروشنده باید دقیقاً یک هزینه ارسال معتبر انتخاب شود.")
    quotes = list(
        ShippingQuote.objects.select_for_update().select_related("vendor_listing").filter(
            uuid__in=normalized_ids,
            user=user,
            cart_item__cart=cart,
            status=ShippingQuote.Status.VALID,
            expires_at__gt=now,
        )
    )
    if len(quotes) != len(grouped):
        raise ValidationError("یکی از استعلام‌های ارسال منقضی یا نامعتبر است؛ هزینه ارسال را دوباره محاسبه کنید.")
    quote_by_vendor = {}
    for quote in quotes:
        vendor_id = quote.vendor_listing.vendor_id
        if vendor_id in quote_by_vendor:
            raise ValidationError("برای یک فروشنده بیش از یک استعلام ارسال ثبت شده است.")
        quote_by_vendor[vendor_id] = quote
    address_hash = address_fingerprint(user=user, address=address)
    total = 0
    for vendor_id, group_items in grouped.items():
        quote = quote_by_vendor.get(vendor_id)
        if not quote or quote.cart_item_id not in {item.id for item in group_items}:
            raise ValidationError("استعلام ارسال با فروشنده یا سبد فعلی مطابقت ندارد.")
        vendor = listing_map[group_items[0].vendor_listing_id].vendor
        payload, group_fingerprint, listings = _vendor_group_quote_payload(
            items=group_items, vendor=vendor, address=address, user=user, lock_listings=True,
        )
        request_snapshot = quote.provider_payload.get("request") or {}
        if (
            quote.vendor_listing.vendor_id != vendor_id
            or quote.address_fingerprint != address_hash
            or quote.quantity != payload["quantity"]
            or quote.provider_payload.get("group_fingerprint") != group_fingerprint
            or request_snapshot.get("cart_items_fingerprint") != group_fingerprint
            or request_snapshot.get("cart_item_ids") != payload["cart_item_ids"]
            or request_snapshot.get("listing_ids") != payload["listing_ids"]
            or request_snapshot.get("vendor_id") != vendor.pk
            or request_snapshot.get("origin_postal_code") != vendor.pickup_postal_code
            or request_snapshot.get("destination_postal_code") != address.postal_code
            or any(request_snapshot.get(key) != payload[key] for key in (
                "declared_value", "weight_grams", "length_cm", "width_cm", "height_cm", "quantity"
            ))
        ):
            raise ValidationError("استعلام ارسال با آدرس، فروشنده، قیمت یا بسته‌بندی فعلی مطابقت ندارد.")
        total += quote.amount
    ShippingQuote.objects.filter(id__in=[quote.id for quote in quotes]).update(
        status=ShippingQuote.Status.CONSUMED,
        used_at=now,
    )
    return total, quotes


def reconcile_shipment_actual_cost(*, shipment: Shipment, actual_cost: int, actor=None):
    """Reconcile final carrier cost against collected shipping funds and the quote.

    Central-account shipping is posted as:
    Dr shipping funds payable (up to the amount collected)
    Dr shipping expense (only any excess over collected funds)
    Cr carrier payable (actual carrier invoice).
    A lower final cost leaves the residual shipping amount pending policy review;
    it is never silently treated as platform revenue.
    """
    actual_cost = int(actual_cost)
    if actual_cost < 0:
        raise ValidationError("هزینه واقعی حمل نمی‌تواند منفی باشد.")
    with transaction.atomic():
        locked = Shipment.objects.select_for_update().select_related("vendor_order", "vendor_order__vendor").get(pk=shipment.pk)
        previous = locked.actual_cost
        if previous == actual_cost:
            return locked, False
        locked.actual_cost = actual_cost
        locked.save(update_fields=("actual_cost", "updated_at"))
        vendor_order = locked.vendor_order
        VendorOrder.objects.filter(pk=vendor_order.pk).update(
            shipping_cost_actual=Shipment.objects.filter(vendor_order=vendor_order, actual_cost__isnull=False).aggregate(total=Sum("actual_cost"))["total"] or 0,
            updated_at=timezone.now(),
        )
        record_external_reconciliation(
            source=FinancialReconciliation.Source.CARRIER_INVOICE,
            external_reference=f"{locked.uuid}:{actual_cost}",
            internal_reference=vendor_order.order.number,
            expected_amount=locked.quoted_cost,
            actual_amount=actual_cost,
            currency=vendor_order.currency,
            details={
                "shipment_uuid": str(locked.uuid),
                "provider": locked.provider,
                "quoted_cost": locked.quoted_cost,
                "customer_charge": locked.customer_charge,
                "previous_actual_cost": previous,
            },
            actor=actor,
        )
        if locked.payer != Shipment.Payer.PLATFORM:
            return locked, True
        funds_account = get_system_account("shipping_funds_payable", "وجوه تخصیص‌یافته به حمل", LedgerAccount.Kind.LIABILITY, vendor_order.currency)
        expense_account = get_system_account("shipping_expense", "هزینه حمل‌ونقل", LedgerAccount.Kind.EXPENSE, vendor_order.currency)
        carrier_payable = get_system_account("carrier_payable", "بدهی به شرکت حمل‌ونقل", LedgerAccount.Kind.LIABILITY, vendor_order.currency)

        charge = int(locked.customer_charge or 0)
        old_funds = min(int(previous or 0), charge)
        new_funds = min(actual_cost, charge)
        old_expense = max(int(previous or 0) - charge, 0)
        new_expense = max(actual_cost - charge, 0)
        funds_delta = new_funds - old_funds
        expense_delta = new_expense - old_expense
        carrier_delta = actual_cost - int(previous or 0)
        lines = []
        if funds_delta > 0:
            lines.append({"account": funds_account, "debit": funds_delta, "credit": 0, "memo": str(locked.uuid)})
        elif funds_delta < 0:
            lines.append({"account": funds_account, "debit": 0, "credit": abs(funds_delta), "memo": str(locked.uuid)})
        if expense_delta > 0:
            lines.append({"account": expense_account, "debit": expense_delta, "credit": 0, "memo": str(locked.uuid)})
        elif expense_delta < 0:
            lines.append({"account": expense_account, "debit": 0, "credit": abs(expense_delta), "memo": str(locked.uuid)})
        if carrier_delta > 0:
            lines.append({"account": carrier_payable, "debit": 0, "credit": carrier_delta, "memo": str(locked.uuid)})
        elif carrier_delta < 0:
            lines.append({"account": carrier_payable, "debit": abs(carrier_delta), "credit": 0, "memo": str(locked.uuid)})
        if lines:
            post_journal(
                idempotency_key=f"shipment-cost:{locked.uuid}:{previous if previous is not None else 'none'}:{actual_cost}",
                kind="shipping_cost",
                description=f"تطبیق هزینه نهایی حمل مرسوله {locked.tracking_number or locked.uuid}",
                lines=lines,
                vendor_order=vendor_order,
                created_by=actor,
                metadata={
                    "shipment_uuid": str(locked.uuid),
                    "quoted_cost": locked.quoted_cost,
                    "customer_charge": charge,
                    "previous_actual_cost": previous,
                    "actual_cost": actual_cost,
                    "delta": carrier_delta,
                    "provider": locked.provider,
                },
            )
        return locked, True


def account_balance(account: LedgerAccount) -> int:
    totals = account.lines.filter(entry__status__in=[JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED]).aggregate(
        debit=Sum("debit"), credit=Sum("credit")
    )
    debit = int(totals["debit"] or 0)
    credit = int(totals["credit"] or 0)
    if account.kind in {LedgerAccount.Kind.ASSET, LedgerAccount.Kind.EXPENSE}:
        return debit - credit
    return credit - debit


def trial_balance(*, currency="IRT"):
    """Return posted-account totals; total debits and credits must reconcile."""
    rows = []
    total_debit = total_credit = 0
    accounts = LedgerAccount.objects.filter(currency=currency, is_active=True).order_by("code")
    for account in accounts:
        totals = account.lines.filter(entry__status__in=[JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED]).aggregate(
            debit=Sum("debit"), credit=Sum("credit")
        )
        debit, credit = int(totals["debit"] or 0), int(totals["credit"] or 0)
        if debit or credit:
            rows.append({"account": account.code, "name": account.name, "debit": debit, "credit": credit, "balance": account_balance(account)})
        total_debit += debit
        total_credit += credit
    return {
        "currency": currency,
        "rows": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "balanced": total_debit == total_credit,
    }


def record_full_order_refund(*, order, refund_reference: str, refund_confirmed: bool, refund_source="bank", actor=None):
    """Record a confirmed full refund as a new financial event.

    The refund is not a blind reversal of the original receipt: gateway funds
    may already have settled to the bank, and shipping funds may have their own
    liability account. Post a new, balanced refund journal to the actual source.
    """
    from apps.orders.models import Order

    refund_reference = str(refund_reference or "").strip()
    if not refund_confirmed or not refund_reference:
        raise ValidationError("برای ثبت بازپرداخت باید تأیید قطعی سرویس پرداخت و شناسه مرجع وجود داشته باشد.")
    if refund_source not in {"bank", "gateway_clearing"}:
        raise ValidationError("منبع بازپرداخت باید حساب بانکی یا مانده درگاه باشد.")
    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)
        refund_key = f"order-refund:{locked_order.uuid}"
        if locked_order.payment_status == Order.PaymentStatus.REFUNDED:
            existing = JournalEntry.objects.filter(idempotency_key=refund_key).first()
            if existing:
                return existing, False
            raise ValidationError("سفارش بازپرداخت‌شده است اما سند مالی آن پیدا نشد؛ بررسی لازم است.")
        if locked_order.payment_status != Order.PaymentStatus.PAID:
            raise ValidationError("فقط سفارش پرداخت‌شده را می‌توان بازپرداخت کرد.")
        shipped_orders = VendorOrder.objects.filter(
            order=locked_order,
            status__in=[VendorOrder.Status.SHIPPED, VendorOrder.Status.DELIVERED, VendorOrder.Status.DISPUTED],
        ).exists()
        booked_shipments = Shipment.objects.filter(
            vendor_order__order=locked_order,
            status__in=[
                Shipment.Status.BOOKED, Shipment.Status.PICKUP_REQUESTED,
                Shipment.Status.HANDED_OVER, Shipment.Status.IN_TRANSIT,
                Shipment.Status.DELIVERED, Shipment.Status.RETURNED,
            ],
        ).exists()
        if shipped_orders or booked_shipments:
            raise ValidationError("این سفارش وارد فرایند ارسال شده است؛ بازپرداخت باید همراه با گردش مرجوعی و هزینه حمل انجام شود.")
        original = JournalEntry.objects.filter(
            idempotency_key=f"order-paid:{locked_order.uuid}",
            status=JournalEntry.Status.POSTED,
        ).first()
        if not original:
            raise ValidationError("سند مالی اصلی سفارش پیدا نشد؛ بازپرداخت حسابداری متوقف شد.")
        vendor_orders = list(VendorOrder.objects.filter(order=locked_order).select_related("vendor"))
        if not vendor_orders:
            raise ValidationError("برای سفارش سند سهم فروشنده وجود ندارد؛ بازپرداخت خودکار متوقف شد.")
        lines = []
        for vendor_order in vendor_orders:
            payable_account = get_system_account(
                f"vendor_payable_{vendor_order.vendor_id}",
                f"بستانکاری فروشنده: {vendor_order.vendor.store_name}",
                LedgerAccount.Kind.LIABILITY,
                locked_order.currency,
                vendor=vendor_order.vendor,
            )
            commission_account = get_system_account(
                "platform_commission_revenue",
                "درآمد کمیسیون پلتفرم",
                LedgerAccount.Kind.REVENUE,
                locked_order.currency,
            )
            if vendor_order.vendor_payable:
                lines.append({"account": payable_account, "debit": vendor_order.vendor_payable, "credit": 0, "memo": refund_reference})
            if vendor_order.commission_amount:
                lines.append({"account": commission_account, "debit": vendor_order.commission_amount, "credit": 0, "memo": refund_reference})
        if locked_order.shipping_amount:
            shipping_funds = get_system_account(
                "shipping_funds_payable", "وجوه تخصیص‌یافته به حمل",
                LedgerAccount.Kind.LIABILITY, locked_order.currency,
            )
            lines.append({"account": shipping_funds, "debit": locked_order.shipping_amount, "credit": 0, "memo": refund_reference})
        refund_account = (
            get_system_account("platform_bank", "حساب بانکی پلتفرم", LedgerAccount.Kind.ASSET, locked_order.currency)
            if refund_source == "bank"
            else get_system_account("gateway_clearing", "وجوه در انتظار تسویه درگاه", LedgerAccount.Kind.ASSET, locked_order.currency)
        )
        lines.append({"account": refund_account, "debit": 0, "credit": locked_order.total_amount, "memo": refund_reference})
        reversal, created = post_journal(
            idempotency_key=refund_key,
            kind="order_refund",
            description=f"بازپرداخت کامل سفارش {locked_order.number}",
            lines=lines,
            order=locked_order,
            created_by=actor,
            metadata={
                "refund_reference": refund_reference,
                "refund_source": refund_source,
                "amount": locked_order.total_amount,
                "original_entry_id": original.id,
            },
        )
        record_external_reconciliation(
            source=FinancialReconciliation.Source.PAYMENT_GATEWAY,
            external_reference=f"refund:{refund_reference}",
            internal_reference=locked_order.number,
            expected_amount=locked_order.total_amount,
            actual_amount=locked_order.total_amount,
            details={"order_uuid": str(locked_order.uuid), "refund_source": refund_source, "journal_entry_id": reversal.id},
            actor=actor,
        )
        locked_order.payment_status = Order.PaymentStatus.REFUNDED
        locked_order.status = Order.Status.REFUNDED
        locked_order.payment_reference = f"{locked_order.payment_reference}|REFUND:{refund_reference}"[:120]
        locked_order.save(update_fields=("payment_status", "status", "payment_reference", "updated_at"))
        VendorOrder.objects.filter(order=locked_order).exclude(status=VendorOrder.Status.DELIVERED).update(
            status=VendorOrder.Status.CANCELLED,
            updated_at=timezone.now(),
        )
        return reversal, created


def record_carrier_invoice_payment(*, invoice_reference: str, amount: int, actor=None, provider_reference=""):
    """Record a confirmed payment against the central carrier payable balance."""
    invoice_reference = str(invoice_reference or "").strip()
    amount = int(amount)
    if not invoice_reference or amount <= 0:
        raise ValidationError("شناسه صورتحساب و مبلغ پرداختی مثبت الزامی است.")
    with transaction.atomic():
        payable = get_system_account("carrier_payable", "بدهی به شرکت حمل‌ونقل", LedgerAccount.Kind.LIABILITY)
        clearing = get_system_account("platform_bank", "حساب بانکی پلتفرم", LedgerAccount.Kind.ASSET)
        reference = str(provider_reference or invoice_reference).strip()[:180]
        idempotency_key = f"carrier-payment:{invoice_reference}"
        lines = [
            {"account": payable, "debit": amount, "credit": 0, "memo": reference},
            {"account": clearing, "debit": 0, "credit": amount, "memo": reference},
        ]
        existing = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
        if not existing:
            available = account_balance(payable)
            if available < amount:
                raise ValidationError(f"مبلغ پرداختی از بدهی ثبت‌شده به شرکت حمل بیشتر است؛ مانده ثبت‌شده {available}.")
        entry, created = post_journal(
            idempotency_key=idempotency_key,
            kind="carrier_payment",
            description=f"پرداخت صورتحساب حمل {invoice_reference}",
            lines=lines,
            created_by=actor,
            metadata={"invoice_reference": invoice_reference, "provider_reference": reference},
        )
        record_external_reconciliation(
            source=FinancialReconciliation.Source.CARRIER_INVOICE,
            external_reference=f"payment:{invoice_reference}",
            internal_reference=entry.idempotency_key,
            expected_amount=amount,
            actual_amount=amount,
            details={"provider_reference": reference, "journal_entry_id": entry.id},
            actor=actor,
        )
        return entry, created



def record_gateway_settlement(*, settlement_reference: str, gross_amount: int, net_amount: int, fee_amount: int, actual_bank_amount=None, actor=None):
    """Record the gateway-to-bank transfer and its fee, then reconcile the bank deposit."""
    reference = str(settlement_reference or "").strip()
    gross, net, fee = int(gross_amount), int(net_amount), int(fee_amount)
    actual = None if actual_bank_amount in (None, "") else int(actual_bank_amount)
    if not reference:
        raise ValidationError("شناسه تسویه درگاه الزامی است.")
    if min(gross, net, fee) < 0 or gross <= 0:
        raise ValidationError("مبالغ تسویه درگاه معتبر نیستند.")
    if gross != net + fee:
        raise ValidationError("مبلغ ناخالص باید برابر مجموع مبلغ خالص و کارمزد باشد.")
    if actual is not None and actual < 0:
        raise ValidationError("مبلغ واریزی بانک نمی‌تواند منفی باشد.")
    with transaction.atomic():
        clearing = get_system_account("gateway_clearing", "وجوه در انتظار تسویه درگاه", LedgerAccount.Kind.ASSET)
        bank = get_system_account("platform_bank", "حساب بانکی پلتفرم", LedgerAccount.Kind.ASSET)
        fee_account = get_system_account("payment_fee_expense", "هزینه کارمزد درگاه", LedgerAccount.Kind.EXPENSE)
        lines = [
            {"account": bank, "debit": net, "credit": 0, "memo": reference},
            {"account": clearing, "debit": 0, "credit": gross, "memo": reference},
        ]
        if fee:
            lines.append({"account": fee_account, "debit": fee, "credit": 0, "memo": reference})
        entry, created = post_journal(
            idempotency_key=f"gateway-settlement:{reference}",
            kind="gateway_settlement",
            description=f"تسویه درگاه به حساب بانکی {reference}",
            lines=lines,
            created_by=actor,
            metadata={"settlement_reference": reference, "gross_amount": gross, "net_amount": net, "fee_amount": fee},
        )
        record_external_reconciliation(
            source=FinancialReconciliation.Source.BANK_STATEMENT,
            external_reference=f"gateway-settlement:{reference}",
            internal_reference=entry.idempotency_key,
            expected_amount=net,
            actual_amount=actual,
            details={"gross_amount": gross, "net_amount": net, "fee_amount": fee, "journal_entry_id": entry.id},
            actor=actor,
        )
        return entry, created
