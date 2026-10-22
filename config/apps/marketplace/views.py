from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .carriers import CarrierError, CarrierNotConfigured, get_carrier, validate_quote_input
from apps.orders.models import Cart, CartItem
from apps.users.models import Address
from apps.shop.models import Product
from .models import CategoryRequest, FinancialReconciliation, SettlementBatch, Shipment, Vendor, VendorOrder, VendorProduct, WholesalePriceTier
from .services import approve_settlement, create_shipping_quote, mark_vendor_order_delivered, reconcile_shipment_actual_cost, record_carrier_invoice_payment, record_external_reconciliation, record_gateway_settlement, record_payout_result, trial_balance
from .payouts import PayoutError, PayoutNotConfigured, submit_settlement_payout


def _json_body(request):
    try:
        value = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("بدنه درخواست JSON معتبر نیست.") from exc
    if not isinstance(value, dict):
        raise ValidationError("بدنه درخواست باید یک شیء JSON باشد.")
    return value


def _error(message, status=400):
    return JsonResponse({"ok": False, "error": str(message)}, status=status)


@login_required
@require_POST
def cart_shipping_quote_api(request):
    """Create a short-lived quote for one seller-owned cart line."""
    try:
        payload = _json_body(request)
        cart = Cart.objects.filter(user=request.user, status=Cart.Status.ACTIVE).first()
        if not cart:
            return _error("سبد خرید فعال پیدا نشد.", 404)
        item = get_object_or_404(
            CartItem.objects.select_related("vendor_listing__vendor", "product"),
            pk=payload.get("cart_item_id"),
            cart=cart,
        )
        address = get_object_or_404(
            Address.objects.select_related("city", "city__province"),
            pk=payload.get("address_id"),
            user=request.user,
        )
        quote = create_shipping_quote(
            user=request.user,
            cart_item=item,
            address=address,
            provider=payload.get("provider", "tipax"),
        )
        return JsonResponse({
            "ok": True,
            "quote_id": str(quote.uuid),
            "cart_item_id": item.id,
            "provider": quote.provider,
            "amount": quote.amount,
            "currency": quote.currency,
            "expires_at": quote.expires_at.isoformat(),
            "message": "هزینه ارسال برآورد شد؛ قیمت نهایی ممکن است در صورتحساب شرکت حمل متفاوت باشد.",
        })
    except PermissionDenied as exc:
        return _error(exc, 403)
    except CarrierNotConfigured as exc:
        return _error(exc, 503)
    except CarrierError as exc:
        return _error(exc, 502)
    except ValidationError as exc:
        return _error(exc)
    except (TypeError, ValueError) as exc:
        return _error(exc)


def _vendor_for_user(user):
    try:
        return Vendor.objects.get(user=user)
    except Vendor.DoesNotExist as exc:
        raise PermissionDenied("حساب فروشندگی برای این کاربر ثبت نشده است.") from exc


def _vendor_order_for_user(user, order_id):
    vendor = _vendor_for_user(user)
    return get_object_or_404(
        VendorOrder.objects.select_related("vendor", "order"),
        pk=order_id,
        vendor=vendor,
    )


@login_required
def vendor_dashboard_page(request):
    try:
        vendor = _vendor_for_user(request.user)
    except PermissionDenied:
        return HttpResponseForbidden("این حساب به پنل فروشنده دسترسی ندارد.")
    return render(request, "marketplace/vendor_dashboard.html", {"vendor": vendor})


@login_required
@require_POST
def vendor_shipping_profile_api(request):
    try:
        vendor = _vendor_for_user(request.user)
        payload = _json_body(request)
        allowed = {"pickup_postal_code", "pickup_address", "pickup_city", "pickup_province", "contact_phone"}
        if set(payload) - allowed:
            return _error("فقط اطلاعات مبدأ ارسال قابل ویرایش است.")
        postal = str(payload.get("pickup_postal_code", vendor.pickup_postal_code)).strip()
        if postal and (len(postal) != 10 or not postal.isdigit()):
            return _error("کد پستی مبدأ باید ۱۰ رقم باشد.")
        for field in allowed.intersection(payload):
            setattr(vendor, field, str(payload[field] or "").strip())
        vendor.save(update_fields=tuple(allowed.intersection(payload)) + ("updated_at",))
        return JsonResponse({"ok": True, "pickup_postal_code": vendor.pickup_postal_code, "message": "اطلاعات مبدأ ارسال ذخیره شد."})
    except PermissionDenied as exc:
        return _error(exc, 403)
    except (TypeError, ValueError) as exc:
        return _error(exc)


@login_required
@require_GET
def vendor_dashboard_api(request):
    try:
        vendor = _vendor_for_user(request.user)
    except PermissionDenied as exc:
        return _error(exc, 403)
    orders = vendor.orders.all()
    pending = orders.filter(status__in=[VendorOrder.Status.NEW, VendorOrder.Status.ACCEPTED, VendorOrder.Status.PREPARING, VendorOrder.Status.READY_TO_SHIP]).count()
    delivered = orders.filter(status=VendorOrder.Status.DELIVERED).count()
    payable = sum(
        batch.payable_amount for batch in vendor.settlements.filter(
            status__in=[SettlementBatch.Status.PENDING_APPROVAL, SettlementBatch.Status.APPROVED, SettlementBatch.Status.PROCESSING, SettlementBatch.Status.FAILED]
        )
    )
    paid = sum(batch.payable_amount for batch in vendor.settlements.filter(status=SettlementBatch.Status.PAID))
    return JsonResponse({
        "ok": True,
        "vendor": {"id": vendor.id, "store_name": vendor.store_name, "status": vendor.status},
        "orders": {"pending_fulfilment": pending, "delivered": delivered, "total": orders.count()},
        "settlement": {"pending_amount": payable, "paid_amount": paid, "currency": "IRT"},
    })


@login_required
@require_GET
def vendor_settlements_api(request):
    try:
        vendor = _vendor_for_user(request.user)
    except PermissionDenied as exc:
        return _error(exc, 403)
    batches = vendor.settlements.order_by("-created_at")[:100]
    return JsonResponse({"ok": True, "results": [{
        "id": batch.id,
        "uuid": str(batch.uuid),
        "status": batch.status,
        "status_label": batch.get_status_display(),
        "period_start": batch.period_start.isoformat(),
        "period_end": batch.period_end.isoformat(),
        "gross_amount": batch.gross_amount,
        "commission_amount": batch.commission_amount,
        "payable_amount": batch.payable_amount,
        "payout_reference": batch.payout_reference,
        "failure_reason": batch.failure_reason,
        "created_at": batch.created_at.isoformat(),
        "paid_at": batch.paid_at.isoformat() if batch.paid_at else None,
    } for batch in batches]})


@login_required
@require_GET
def vendor_orders_api(request):
    try:
        vendor = _vendor_for_user(request.user)
    except PermissionDenied as exc:
        return _error(exc, 403)
    orders = vendor.orders.select_related("order").prefetch_related("shipments").order_by("-created_at")[:100]
    return JsonResponse({"ok": True, "results": [{
        "id": item.id,
        "uuid": str(item.uuid),
        "order_number": item.order.number,
        "status": item.status,
        "status_label": item.get_status_display(),
        "items": item.items_snapshot,
        "subtotal": item.subtotal,
        "shipping_charge": item.customer_shipping_amount,
        "commission": item.commission_amount,
        "vendor_payable": item.vendor_payable,
        "currency": item.currency,
        "created_at": item.created_at.isoformat(),
        "recipient": {
            "name": item.order.shipping_recipient,
            "phone": item.order.shipping_phone,
            "province": item.order.shipping_province,
            "city": item.order.shipping_city,
            "postal_code": item.order.shipping_postal_code,
            "address": item.order.shipping_address,
        },
        "customer_note": item.order.customer_note,
        "shipments": [{
            "uuid": str(shipment.uuid),
            "provider": shipment.provider,
            "status": shipment.status,
            "tracking_number": shipment.tracking_number,
            "quoted_cost": shipment.quoted_cost,
            "actual_cost": shipment.actual_cost,
            "label_url": shipment.label_url,
        } for shipment in item.shipments.all()],
    } for item in orders]})


@login_required
@require_GET
def vendor_catalog_products_api(request):
    try:
        vendor = _vendor_for_user(request.user)
    except PermissionDenied as exc:
        return _error(exc, 403)
    query = str(request.GET.get("q", "")).strip()
    if len(query) < 2:
        return JsonResponse({"ok": True, "results": []})
    products = Product.objects.filter(
        is_active=True,
        category__is_active=True,
        name__icontains=query,
    ).select_related("category").order_by("name")[:30]
    return JsonResponse({"ok": True, "results": [{
        "id": product.id,
        "name": product.name,
        "category": product.category.name,
    } for product in products]})


@login_required
def vendor_products_api(request):
    try:
        vendor = _vendor_for_user(request.user)
    except PermissionDenied as exc:
        return _error(exc, 403)
    if request.method == "GET":
        listings = vendor.listings.select_related("product", "product__category").prefetch_related("wholesale_tiers").order_by("-created_at")
        return JsonResponse({"ok": True, "results": [{
            "id": listing.id,
            "product_id": listing.product_id,
            "product_name": listing.product.name,
            "status": listing.status,
            "retail_price": listing.retail_price,
            "compare_at_price": listing.compare_at_price,
            "stock_quantity": listing.stock_quantity,
            "wholesale_enabled": listing.wholesale_enabled,
            "wholesale_tiers": [{"id": tier.id, "minimum_quantity": tier.minimum_quantity, "unit_price": tier.unit_price} for tier in listing.wholesale_tiers.all()],
            "supports_custom_printing": listing.supports_custom_printing,
            "weight_grams": listing.weight_grams,
            "package_dimensions_cm": [listing.package_length_cm, listing.package_width_cm, listing.package_height_cm],
            "handling_days": listing.handling_days,
        } for listing in listings]})
    if request.method != "POST":
        return _error("متد درخواست پشتیبانی نمی‌شود.", 405)
    try:
        payload = _json_body(request)
        if not vendor.can_receive_orders:
            return _error("فروشنده تا زمان تأیید و فعال‌شدن حساب نمی‌تواند محصول ثبت کند.", 403)
        product = get_object_or_404(Product, pk=payload.get("product_id"), is_active=True, category__is_active=True)
        if vendor.listings.filter(product=product).exists():
            return _error("این محصول قبلاً توسط فروشگاه شما ثبت شده است.", 409)
        listing = VendorProduct(
            vendor=vendor,
            product=product,
            status=VendorProduct.Status.PENDING,
            retail_price=int(payload.get("retail_price", 0)),
            compare_at_price=payload.get("compare_at_price") or None,
            stock_quantity=int(payload.get("stock_quantity", 0)),
            wholesale_enabled=payload.get("wholesale_enabled") is True,
            supports_custom_printing=payload.get("supports_custom_printing") is True,
            weight_grams=int(payload.get("weight_grams", 0)),
            package_length_cm=int(payload.get("package_length_cm", 0)),
            package_width_cm=int(payload.get("package_width_cm", 0)),
            package_height_cm=int(payload.get("package_height_cm", 0)),
            handling_days=int(payload.get("handling_days", 2)),
        )
        listing.full_clean()
        listing.save()
        return JsonResponse({"ok": True, "listing_id": listing.id, "status": listing.status, "message": "محصول برای بررسی مدیر ثبت شد."}, status=201)
    except (ValidationError, TypeError, ValueError) as exc:
        return _error(exc)


@login_required
@require_POST
def vendor_product_update_api(request, listing_id):
    try:
        vendor = _vendor_for_user(request.user)
        payload = _json_body(request)
        with transaction.atomic():
            listing = get_object_or_404(VendorProduct.objects.select_for_update(), pk=listing_id, vendor=vendor)
            allowed = {
                "retail_price", "compare_at_price", "stock_quantity", "wholesale_enabled",
                "supports_custom_printing", "weight_grams", "package_length_cm",
                "package_width_cm", "package_height_cm", "handling_days",
            }
            unknown = set(payload) - allowed
            if unknown:
                return _error("فیلدهای غیرمجاز: " + ", ".join(sorted(unknown)))
            price_changed = False
            for field in allowed.intersection(payload):
                value = payload[field]
                if field in {"retail_price", "stock_quantity", "weight_grams", "package_length_cm", "package_width_cm", "package_height_cm", "handling_days"}:
                    value = int(value)
                elif field == "compare_at_price":
                    value = None if value in (None, "") else int(value)
                elif field in {"wholesale_enabled", "supports_custom_printing"}:
                    if not isinstance(value, bool):
                        return _error(f"{field} باید true یا false باشد.")
                if field in {"retail_price", "compare_at_price"} and getattr(listing, field) != value:
                    price_changed = True
                setattr(listing, field, value)
            if listing.status == VendorProduct.Status.ACTIVE and price_changed:
                listing.status = VendorProduct.Status.PENDING
            listing.full_clean()
            listing.save()
        return JsonResponse({"ok": True, "listing_id": listing.id, "status": listing.status, "price_reapproval_required": price_changed})
    except PermissionDenied as exc:
        return _error(exc, 403)
    except (ValidationError, TypeError, ValueError) as exc:
        return _error(exc)


@login_required
@require_POST
def vendor_wholesale_tier_api(request, listing_id):
    try:
        vendor = _vendor_for_user(request.user)
        payload = _json_body(request)
        listing = get_object_or_404(VendorProduct, pk=listing_id, vendor=vendor)
        if listing.status not in {VendorProduct.Status.ACTIVE, VendorProduct.Status.PENDING, VendorProduct.Status.DRAFT}:
            return _error("وضعیت فعلی محصول اجازه تغییر قیمت عمده را نمی‌دهد.", 409)
        minimum = int(payload.get("minimum_quantity", 0))
        unit_price = int(payload.get("unit_price", 0))
        tier = WholesalePriceTier(listing=listing, minimum_quantity=minimum, unit_price=unit_price)
        tier.full_clean()
        with transaction.atomic():
            tier.save()
            listing.wholesale_enabled = True
            if listing.status == VendorProduct.Status.ACTIVE:
                listing.status = VendorProduct.Status.PENDING
            listing.save(update_fields=("wholesale_enabled", "status", "updated_at"))
        return JsonResponse({"ok": True, "tier_id": tier.id, "minimum_quantity": tier.minimum_quantity, "unit_price": tier.unit_price}, status=201)
    except PermissionDenied as exc:
        return _error(exc, 403)
    except (ValidationError, TypeError, ValueError) as exc:
        return _error(exc)


@login_required
@require_POST
def vendor_wholesale_tier_delete_api(request, tier_id):
    try:
        vendor = _vendor_for_user(request.user)
        with transaction.atomic():
            tier = get_object_or_404(WholesalePriceTier.objects.select_for_update(), pk=tier_id, listing__vendor=vendor)
            listing = tier.listing
            tier.delete()
            if listing.status == VendorProduct.Status.ACTIVE:
                listing.status = VendorProduct.Status.PENDING
                listing.save(update_fields=("status", "updated_at"))
        return JsonResponse({"ok": True, "deleted": True})
    except PermissionDenied as exc:
        return _error(exc, 403)


@login_required
@require_POST
def vendor_category_request_api(request):
    try:
        vendor = _vendor_for_user(request.user)
        payload = _json_body(request)
        if not vendor.can_receive_orders:
            return _error("فروشنده باید ابتدا تأیید شود.", 403)
        category_request = CategoryRequest(
            vendor=vendor,
            name=str(payload.get("name", "")).strip(),
            description=str(payload.get("description", "")).strip(),
        )
        category_request.full_clean()
        category_request.save()
        return JsonResponse({"ok": True, "request_id": category_request.id, "status": category_request.status}, status=201)
    except PermissionDenied as exc:
        return _error(exc, 403)
    except (ValidationError, TypeError, ValueError) as exc:
        return _error(exc)


@login_required
@require_POST
def vendor_order_action_api(request, order_id):
    try:
        vendor_order = _vendor_order_for_user(request.user, order_id)
        payload = _json_body(request)
        action = payload.get("action")
        transitions = {
            VendorOrder.Status.NEW: {"accept": VendorOrder.Status.ACCEPTED, "cancel": VendorOrder.Status.CANCELLED},
            VendorOrder.Status.ACCEPTED: {"prepare": VendorOrder.Status.PREPARING, "cancel": VendorOrder.Status.CANCELLED},
            VendorOrder.Status.PREPARING: {"ready_to_ship": VendorOrder.Status.READY_TO_SHIP, "cancel": VendorOrder.Status.CANCELLED},
        }
        with transaction.atomic():
            locked = VendorOrder.objects.select_for_update().get(pk=vendor_order.pk)
            next_status = transitions.get(locked.status, {}).get(action)
            if not next_status:
                return _error("این عملیات برای وضعیت فعلی سفارش مجاز نیست.", 409)
            if action == "cancel" and locked.order.payment_status == "paid":
                return _error("لغو سفارش پرداخت‌شده باید از فرایند رسمی لغو/بازپرداخت انجام شود.", 409)
            locked.status = next_status
            locked.save(update_fields=("status", "updated_at"))
        return JsonResponse({"ok": True, "vendor_order_id": locked.id, "status": locked.status})
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ValidationError as exc:
        return _error(exc)
    except (ValueError, TypeError) as exc:
        return _error(exc)


@login_required
@require_POST
def shipment_quote_api(request, order_id):
    try:
        vendor_order = _vendor_order_for_user(request.user, order_id)
        if vendor_order.status != VendorOrder.Status.READY_TO_SHIP:
            return _error("برای استعلام نهایی، سفارش باید ابتدا آماده ارسال شود.", 409)
        active_shipment = Shipment.objects.filter(
            vendor_order=vendor_order,
            status__in=[
                Shipment.Status.QUOTED, Shipment.Status.BOOKED,
                Shipment.Status.PICKUP_REQUESTED, Shipment.Status.HANDED_OVER,
                Shipment.Status.IN_TRANSIT, Shipment.Status.EXCEPTION,
            ],
        ).exists()
        if active_shipment:
            return _error("برای این سفارش قبلاً مرسوله فعال ثبت شده است؛ ابتدا وضعیت همان مرسوله را مشخص کن.", 409)
        raw_payload = _json_body(request)
        provider = str(raw_payload.get("provider", "tipax")).lower()
        if provider not in {"tipax", "post"}:
            return _error("شرکت حمل‌ونقل انتخاب‌شده پشتیبانی نمی‌شود.")
        if not vendor_order.vendor.pickup_postal_code:
            return _error("کد پستی مبدأ فروشنده در پنل تکمیل نشده است.")
        # The seller may describe the packed parcel, but may not override either
        # postal code or declared value from the immutable order snapshot.
        raw_payload.update({
            "origin_postal_code": vendor_order.vendor.pickup_postal_code,
            "destination_postal_code": vendor_order.order.shipping_postal_code,
            "declared_value": vendor_order.subtotal,
        })
        payload = validate_quote_input(raw_payload)
        quote = get_carrier(provider).quote(payload)
        with transaction.atomic():
            locked_order = VendorOrder.objects.select_for_update().get(pk=vendor_order.pk)
            already_allocated = Shipment.objects.filter(vendor_order=locked_order).aggregate(total=Sum("customer_charge"))["total"] or 0
            customer_charge = max(int(locked_order.customer_shipping_amount) - int(already_allocated), 0)
            shipment = Shipment.objects.create(
                vendor_order=locked_order,
                provider=provider,
                status=Shipment.Status.QUOTED,
                quoted_cost=quote.amount,
                customer_charge=customer_charge,
                quote_reference=quote.reference,
                quote_expires_at=_parse_datetime(quote.expires_at),
                provider_payload={"quote": quote.raw or {}, "request": payload},
            )
        return JsonResponse({
            "ok": True,
            "shipment_id": str(shipment.uuid),
            "provider": provider,
            "quoted_cost": shipment.quoted_cost,
            "currency": quote.currency,
            "quote_reference": shipment.quote_reference,
            "quote_expires_at": shipment.quote_expires_at.isoformat() if shipment.quote_expires_at else None,
            "note": "هزینه برآوردی است؛ هزینه نهایی باید با صورتحساب شرکت حمل تطبیق داده شود.",
        })
    except PermissionDenied as exc:
        return _error(exc, 403)
    except CarrierNotConfigured as exc:
        return _error(exc, 503)
    except CarrierError as exc:
        return _error(exc, 502)
    except ValidationError as exc:
        return _error(exc)
    except (TypeError, ValueError) as exc:
        return _error(exc)


def _parse_datetime(value):
    if not value:
        return None
    from django.utils.dateparse import parse_datetime
    parsed = parse_datetime(str(value))
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


@login_required
@require_POST
def shipment_book_api(request, order_id):
    try:
        vendor_order = _vendor_order_for_user(request.user, order_id)
        payload = _json_body(request)
        shipment_uuid = payload.get("shipment_id")
        with transaction.atomic():
            shipment = get_object_or_404(
                Shipment.objects.select_for_update(),
                uuid=shipment_uuid,
                vendor_order=vendor_order,
                status=Shipment.Status.QUOTED,
            )
            if vendor_order.status != VendorOrder.Status.READY_TO_SHIP:
                return _error("فروشنده باید ابتدا سفارش را آماده ارسال کند.", 409)
            if shipment.quote_expires_at and shipment.quote_expires_at <= timezone.now():
                return _error("مهلت برآورد هزینه تمام شده؛ هزینه را دوباره استعلام کنید.", 409)
            # Mark in-flight before network I/O so concurrent requests cannot
            # book the same shipment twice. On ambiguous errors staff must
            # reconcile the carrier dashboard before retrying.
            shipment.status = Shipment.Status.BOOKED
            shipment.save(update_fields=("status", "updated_at"))
        carrier_payload = {
            **(shipment.provider_payload.get("request") or {}),
            "quote_reference": shipment.quote_reference,
            "recipient": {
                "name": vendor_order.order.shipping_recipient,
                "phone": vendor_order.order.shipping_phone,
                "province": vendor_order.order.shipping_province,
                "city": vendor_order.order.shipping_city,
                "postal_code": vendor_order.order.shipping_postal_code,
                "address": vendor_order.order.shipping_address,
            },
            "order_number": vendor_order.order.number,
            "idempotency_key": str(shipment.uuid),
        }
        try:
            result = get_carrier(shipment.provider).create_shipment(carrier_payload)
        except CarrierNotConfigured as exc:
            # No network request was made when required configuration is absent,
            # so it is safe to return the quote to a retryable state.
            Shipment.objects.filter(pk=shipment.pk).update(
                status=Shipment.Status.QUOTED,
                last_error=str(exc),
                last_event_at=timezone.now(),
            )
            return _error(exc, 503)
        except CarrierError as exc:
            # Network/5xx failures can be ambiguous; keep EXCEPTION until the
            # carrier dashboard is checked to avoid duplicate shipment booking.
            Shipment.objects.filter(pk=shipment.pk).update(
                status=Shipment.Status.EXCEPTION,
                last_error=str(exc),
                last_event_at=timezone.now(),
            )
            return _error(f"{exc} وضعیت ثبت مرسوله را در پنل شرکت بررسی کنید و از ثبت مجدد بدون بررسی خودداری کنید.", 502)
        with transaction.atomic():
            shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
            shipment.external_shipment_id = result["external_shipment_id"]
            shipment.tracking_number = result["tracking_number"]
            shipment.label_url = result["label_url"]
            shipment.provider_payload = {**shipment.provider_payload, "booking": result["raw"]}
            shipment.booked_at = timezone.now()
            shipment.status = Shipment.Status.BOOKED
            shipment.last_error = ""
            shipment.save(update_fields=("external_shipment_id", "tracking_number", "label_url", "provider_payload", "booked_at", "status", "last_error", "updated_at"))
        return JsonResponse({"ok": True, "shipment_id": str(shipment.uuid), "tracking_number": shipment.tracking_number, "label_url": shipment.label_url, "status": shipment.status})
    except PermissionDenied as exc:
        return _error(exc, 403)
    except CarrierNotConfigured as exc:
        return _error(exc, 503)
    except CarrierError as exc:
        return _error(exc, 502)
    except ValidationError as exc:
        return _error(exc)
    except (TypeError, ValueError) as exc:
        return _error(exc)


@login_required
@require_POST
def shipment_handed_over_api(request, order_id, shipment_uuid):
    try:
        vendor_order = _vendor_order_for_user(request.user, order_id)
        shipment = get_object_or_404(Shipment, uuid=shipment_uuid, vendor_order=vendor_order)
        if shipment.status != Shipment.Status.BOOKED:
            return _error("فقط مرسوله ثبت‌شده و دارای کد رهگیری قابل تحویل به شرکت است.", 409)
        shipment.status = Shipment.Status.HANDED_OVER
        shipment.handed_over_at = timezone.now()
        shipment.last_event_at = timezone.now()
        shipment.save(update_fields=("status", "handed_over_at", "last_event_at", "updated_at"))
        vendor_order.status = VendorOrder.Status.SHIPPED
        vendor_order.save(update_fields=("status", "updated_at"))
        return JsonResponse({"ok": True, "shipment_id": str(shipment.uuid), "status": shipment.status})
    except PermissionDenied as exc:
        return _error(exc, 403)


@staff_member_required
@require_POST
def shipment_update_status_api(request, shipment_uuid):
    try:
        payload = _json_body(request)
        target = payload.get("status")
        allowed = {
            Shipment.Status.IN_TRANSIT,
            Shipment.Status.DELIVERED,
            Shipment.Status.DELIVERY_FAILED,
            Shipment.Status.RETURNED,
            Shipment.Status.EXCEPTION,
        }
        if target not in allowed:
            return _error("وضعیت انتخاب‌شده برای به‌روزرسانی مجاز نیست.")
        with transaction.atomic():
            shipment = get_object_or_404(Shipment.objects.select_for_update(), uuid=shipment_uuid)
            if shipment.status in {Shipment.Status.CANCELLED, Shipment.Status.RETURNED}:
                return _error("مرسوله نهایی‌شده قابل تغییر نیست.", 409)
            now = timezone.now()
            shipment.status = target
            shipment.last_event_at = now
            if target == Shipment.Status.DELIVERED:
                shipment.delivered_at = now
                vendor_order = shipment.vendor_order
                mark_vendor_order_delivered(vendor_order, delivered_at=now)
            if target == Shipment.Status.RETURNED:
                shipment.vendor_order.status = VendorOrder.Status.DISPUTED
                shipment.vendor_order.save(update_fields=("status", "updated_at"))
            shipment.save(update_fields=("status", "last_event_at", "delivered_at", "updated_at"))
            if payload.get("actual_cost") is not None:
                reconcile_shipment_actual_cost(
                    shipment=shipment,
                    actual_cost=payload["actual_cost"],
                    actor=request.user,
                )
                shipment.refresh_from_db()
        return JsonResponse({"ok": True, "shipment_id": str(shipment.uuid), "status": shipment.status, "actual_cost": shipment.actual_cost})
    except (PermissionDenied, ValidationError) as exc:
        return _error(exc, 403 if isinstance(exc, PermissionDenied) else 400)
    except (TypeError, ValueError) as exc:
        return _error(exc)


@staff_member_required
@require_GET
def trial_balance_api(request):
    currency = request.GET.get("currency", "IRT")
    if currency != "IRT":
        return _error("در این نسخه فقط ارز IRT پشتیبانی می‌شود.")
    report = trial_balance(currency=currency)
    return JsonResponse({"ok": True, **report})


@staff_member_required
@require_POST
def gateway_settlement_api(request):
    try:
        payload = _json_body(request)
        entry, created = record_gateway_settlement(
            settlement_reference=payload.get("settlement_reference"),
            gross_amount=payload.get("gross_amount"),
            net_amount=payload.get("net_amount"),
            fee_amount=payload.get("fee_amount", 0),
            actual_bank_amount=payload.get("actual_bank_amount"),
            actor=request.user,
        )
        return JsonResponse({
            "ok": True,
            "created": created,
            "journal_entry_id": entry.id,
            "idempotency_key": entry.idempotency_key,
            "status": entry.status,
        })
    except (ValidationError, TypeError, ValueError) as exc:
        return _error(exc)


@staff_member_required
@require_POST
def carrier_invoice_payment_api(request):
    try:
        payload = _json_body(request)
        entry, created = record_carrier_invoice_payment(
            invoice_reference=payload.get("invoice_reference"),
            amount=payload.get("amount"),
            provider_reference=payload.get("provider_reference", ""),
            actor=request.user,
        )
        return JsonResponse({
            "ok": True,
            "created": created,
            "journal_entry_id": entry.id,
            "idempotency_key": entry.idempotency_key,
            "status": entry.status,
        })
    except (ValidationError, TypeError, ValueError) as exc:
        return _error(exc)


@staff_member_required
@require_POST
def external_reconciliation_api(request):
    try:
        payload = _json_body(request)
        source = str(payload.get("source", ""))
        if source not in {choice for choice, _label in FinancialReconciliation.Source.choices}:
            return _error("منبع تطبیق مالی معتبر نیست.")
        record, created = record_external_reconciliation(
            source=source,
            external_reference=payload.get("external_reference"),
            internal_reference=payload.get("internal_reference", ""),
            expected_amount=payload.get("expected_amount"),
            actual_amount=payload.get("actual_amount"),
            currency=payload.get("currency", "IRT"),
            details=payload.get("details") if isinstance(payload.get("details"), dict) else {},
            actor=request.user,
        )
        return JsonResponse({
            "ok": True,
            "created": created,
            "uuid": str(record.uuid),
            "source": record.source,
            "external_reference": record.external_reference,
            "expected_amount": record.expected_amount,
            "actual_amount": record.actual_amount,
            "status": record.status,
            "delta": None if record.expected_amount is None or record.actual_amount is None else record.actual_amount - record.expected_amount,
        })
    except (ValidationError, TypeError, ValueError) as exc:
        return _error(exc)


@staff_member_required
@require_GET
def settlement_queue_api(request):
    batches = SettlementBatch.objects.select_related("vendor", "approved_by").filter(
        status=SettlementBatch.Status.PENDING_APPROVAL
    ).order_by("created_at")
    return JsonResponse({"ok": True, "results": [{
        "id": batch.id,
        "uuid": str(batch.uuid),
        "vendor": batch.vendor.store_name,
        "period_start": batch.period_start.isoformat(),
        "period_end": batch.period_end.isoformat(),
        "gross_amount": batch.gross_amount,
        "commission_amount": batch.commission_amount,
        "payable_amount": batch.payable_amount,
        "order_ids": batch.order_ids,
        "status": batch.status,
    } for batch in batches]})


@staff_member_required
@require_POST
def settlement_approve_api(request, batch_id):
    try:
        batch = approve_settlement(batch_id=batch_id, approver=request.user)
        try:
            batch = submit_settlement_payout(batch.id)
        except PayoutNotConfigured as exc:
            # Approval remains recorded; the batch cannot be paid until the
            # contracted bank/PSP payout API is configured.
            return JsonResponse({
                "ok": True,
                "batch_id": batch.id,
                "status": batch.status,
                "approved_at": batch.approved_at.isoformat(),
                "payout_submitted": False,
                "payout_message": str(exc),
            })
        except PayoutError as exc:
            return _error(exc, 502)
        return JsonResponse({
            "ok": True,
            "batch_id": batch.id,
            "status": batch.status,
            "approved_at": batch.approved_at.isoformat(),
            "payout_submitted": True,
            "payout_reference": batch.payout_reference,
        })
    except (PermissionDenied, ValidationError) as exc:
        return _error(exc, 403 if isinstance(exc, PermissionDenied) else 409)


@staff_member_required
@require_POST
def settlement_record_payout_api(request, batch_id):
    """Internal reconciliation endpoint; call only after an external bank result is confirmed."""
    try:
        payload = _json_body(request)
        batch = record_payout_result(
            batch_id=batch_id,
            provider_reference=str(payload.get("provider_reference", "")),
            succeeded=payload.get("succeeded") is True,
            failure_reason=str(payload.get("failure_reason", "")),
        )
        return JsonResponse({"ok": True, "batch_id": batch.id, "status": batch.status, "payout_reference": batch.payout_reference})
    except (PermissionDenied, ValidationError) as exc:
        return _error(exc, 403 if isinstance(exc, PermissionDenied) else 409)
