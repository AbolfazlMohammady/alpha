from django import template
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.orders.models import Order
from apps.shop.models import Product
from apps.customizer.models import DesignDraft
from apps.users.models import User

register = template.Library()


@register.simple_tag
def get_admin_dashboard():
    today = timezone.localdate()
    orders = Order.objects.all()
    order_stats = orders.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status=Order.Status.PENDING)),
        processing=Count("id", filter=Q(status=Order.Status.PROCESSING)),
        shipped=Count("id", filter=Q(status=Order.Status.SHIPPED)),
        delivered=Count("id", filter=Q(status=Order.Status.DELIVERED)),
        cancelled=Count("id", filter=Q(status=Order.Status.CANCELLED)),
        today=Count("id", filter=Q(created_at__date=today)),
        sales=Sum("total_amount", filter=Q(payment_status=Order.PaymentStatus.PAID)),
    )
    return {
        "products": Product.objects.filter(is_active=True).count(),
        "users": User.objects.filter(is_active=True).count(),
        "orders": order_stats["total"] or 0,
        "pending_orders": order_stats["pending"] or 0,
        "processing_orders": order_stats["processing"] or 0,
        "shipped_orders": order_stats["shipped"] or 0,
        "delivered_orders": order_stats["delivered"] or 0,
        "cancelled_orders": order_stats["cancelled"] or 0,
        "today_orders": order_stats["today"] or 0,
        "sales": order_stats["sales"] or 0,
        "drafts": DesignDraft.objects.count(),
        "recent_orders": list(orders.select_related("user").order_by("-created_at")[:6]),
    }
