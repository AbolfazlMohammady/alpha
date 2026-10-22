from celery import shared_task

from .services import create_daily_settlement_batches


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def create_daily_settlement_batches_task(self):
    """Prepare daily vendor settlement batches; never initiate bank transfers."""
    batches = create_daily_settlement_batches()
    return {"created": len(batches), "batch_ids": [batch.id for batch in batches]}



@shared_task(bind=True, max_retries=2, default_retry_delay=30, acks_late=True)
def refresh_active_shipments_task(self):
    """Poll carrier tracking for active shipments; unknown provider statuses are not guessed."""
    from django.utils import timezone
    from .carriers import CarrierError, CarrierNotConfigured, get_carrier
    from .models import Shipment, VendorOrder
    from .services import mark_vendor_order_delivered, reconcile_shipment_actual_cost

    active_statuses = [
        Shipment.Status.BOOKED,
        Shipment.Status.PICKUP_REQUESTED,
        Shipment.Status.HANDED_OVER,
        Shipment.Status.IN_TRANSIT,
    ]
    rows = Shipment.objects.filter(
        status__in=active_statuses,
        tracking_number__gt="",
    ).select_related("vendor_order", "vendor_order__vendor").order_by("last_event_at", "id")[:100]
    checked = updated = failed = 0
    status_map = {
        "delivered": Shipment.Status.DELIVERED,
        "delivered_to_recipient": Shipment.Status.DELIVERED,
        "تحویل شده": Shipment.Status.DELIVERED,
        "تحویل‌شده": Shipment.Status.DELIVERED,
        "in_transit": Shipment.Status.IN_TRANSIT,
        "in-transit": Shipment.Status.IN_TRANSIT,
        "shipped": Shipment.Status.IN_TRANSIT,
        "moving": Shipment.Status.IN_TRANSIT,
        "handed_over": Shipment.Status.HANDED_OVER,
        "collected": Shipment.Status.HANDED_OVER,
        "returned": Shipment.Status.RETURNED,
        "return": Shipment.Status.RETURNED,
        "delivery_failed": Shipment.Status.DELIVERY_FAILED,
        "undeliverable": Shipment.Status.DELIVERY_FAILED,
    }
    for shipment in rows:
        checked += 1
        try:
            response = get_carrier(shipment.provider).track(shipment.tracking_number)
            raw_status = str(response.get("status") or response.get("state") or response.get("tracking_status") or "").strip().lower()
            target = status_map.get(raw_status)
            now = timezone.now()
            if not target:
                # Keep raw response for later mapping review, but don't invent a
                # delivered state when the provider uses an unknown vocabulary.
                Shipment.objects.filter(pk=shipment.pk).update(
                    provider_payload={**shipment.provider_payload, "last_tracking_response": response},
                    last_event_at=now,
                    last_error="وضعیت پاسخ API هنوز به وضعیت داخلی نگاشت نشده است.",
                    updated_at=now,
                )
                continue
            if target == Shipment.Status.DELIVERED:
                mark_vendor_order_delivered(shipment.vendor_order, delivered_at=now)
                shipment.delivered_at = now
                actual_cost = response.get("actual_cost") or response.get("shipping_cost") or response.get("final_cost")
                if actual_cost is not None:
                    reconcile_shipment_actual_cost(shipment=shipment, actual_cost=actual_cost)
            elif target == Shipment.Status.RETURNED:
                VendorOrder.objects.filter(pk=shipment.vendor_order_id).update(
                    status=VendorOrder.Status.DISPUTED,
                    updated_at=now,
                )
            Shipment.objects.filter(pk=shipment.pk).update(
                status=target,
                delivered_at=shipment.delivered_at,
                provider_payload={**shipment.provider_payload, "last_tracking_response": response},
                last_event_at=now,
                last_error="",
                updated_at=now,
            )
            updated += 1
        except CarrierNotConfigured as exc:
            Shipment.objects.filter(pk=shipment.pk).update(last_error=str(exc)[:2000], updated_at=timezone.now())
            failed += 1
        except CarrierError as exc:
            Shipment.objects.filter(pk=shipment.pk).update(last_error=str(exc)[:2000], updated_at=timezone.now())
            failed += 1
        except Exception:
            # Avoid leaking provider payloads or customer details into task logs.
            Shipment.objects.filter(pk=shipment.pk).update(
                last_error="خطای غیرمنتظره هنگام به‌روزرسانی رهگیری؛ بررسی دستی لازم است.",
                updated_at=timezone.now(),
            )
            failed += 1
    return {"checked": checked, "updated": updated, "failed": failed}
