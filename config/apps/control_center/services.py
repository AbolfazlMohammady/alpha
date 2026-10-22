from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.orders.models import Order


class OrderTransitionError(ValueError):
    """Raised when an order cannot move to the requested workflow stage."""


@transaction.atomic
def start_preparing(order: Order) -> Order:
    locked = Order.objects.select_for_update().get(pk=order.pk)

    if locked.payment_status != Order.PaymentStatus.PAID:
        raise OrderTransitionError("فقط سفارش پرداخت‌شده می‌تواند وارد آماده‌سازی شود.")
    if locked.status != Order.Status.PAID:
        raise OrderTransitionError("این سفارش در وضعیت «پرداخت‌شده» نیست.")

    locked.status = Order.Status.PROCESSING
    locked.shipping_status = Order.ShippingStatus.PREPARING
    locked.save(update_fields=("status", "shipping_status", "updated_at"))
    return locked


@transaction.atomic
def mark_shipped(order: Order) -> Order:
    locked = Order.objects.select_for_update().get(pk=order.pk)

    if locked.payment_status != Order.PaymentStatus.PAID:
        raise OrderTransitionError("سفارش پرداخت موفق ندارد و قابل ارسال نیست.")
    if locked.status != Order.Status.PROCESSING:
        raise OrderTransitionError("ابتدا سفارش را وارد آماده‌سازی کنید.")
    if locked.shipping_status != Order.ShippingStatus.PREPARING:
        raise OrderTransitionError("وضعیت ارسال سفارش برای ثبت ارسال معتبر نیست.")

    now = timezone.now()
    locked.status = Order.Status.SHIPPED
    locked.shipping_status = Order.ShippingStatus.SHIPPED
    locked.shipped_at = locked.shipped_at or now
    locked.save(update_fields=("status", "shipping_status", "shipped_at", "updated_at"))
    return locked


@transaction.atomic
def mark_delivered(order: Order) -> Order:
    locked = Order.objects.select_for_update().get(pk=order.pk)

    if locked.payment_status != Order.PaymentStatus.PAID:
        raise OrderTransitionError("سفارش پرداخت موفق ندارد و قابل تحویل نیست.")
    if locked.status != Order.Status.SHIPPED or locked.shipping_status != Order.ShippingStatus.SHIPPED:
        raise OrderTransitionError("برای ثبت تحویل، سفارش باید ارسال‌شده باشد.")

    now = timezone.now()
    locked.status = Order.Status.DELIVERED
    locked.shipping_status = Order.ShippingStatus.DELIVERED
    locked.delivered_at = locked.delivered_at or now
    locked.save(update_fields=("status", "shipping_status", "delivered_at", "updated_at"))
    return locked


