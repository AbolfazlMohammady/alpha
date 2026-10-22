from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .carriers import CarrierError, CarrierNotConfigured, get_carrier, validate_quote_input
from apps.orders.models import Cart, CartItem
from apps.users.models import Address
from .models import FinancialReconciliation, SettlementBatch, Shipment, Vendor, VendorOrder, VendorProduct
from .services import approve_settlement, create_shipping_quote, mark_vendor_order_delivered, reconcile_shipment_actual_cost, record_external_reconciliation, record_payout_result, trial_balance
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
            status__in=[SettlementBatch.Status.PENDING_APPROVAL, SettlementBatch.Status.APPROVED, SettlementBatch.Status.PROCESSING]
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
        shipment = Shipment.objects.create(
            vendor_order=vendor_order,
            provider=provider,
            status=Shipment.Status.QUOTED,
            quoted_cost=quote.amount,
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
        except CarrierError as exc:
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
