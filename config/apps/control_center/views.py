from django.conf import settings
import json
import html
import mimetypes
from datetime import datetime, time, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.db.models import Case, CharField, Count, Exists, F, IntegerField, Min, OuterRef, Q, Subquery, Sum, Value, When, Prefetch
from django.db.models.functions import Concat, TruncDate, TruncMonth
from django.core.cache import cache
from django.utils import timezone
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.core.paginator import Paginator
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect

from apps.orders.models import Order, OrderItem
from apps.shop.models import Category, ContactPageSettings, Product, ProductColor, ProductComment, ProductImage, ProductSize, ProductVariant
from apps.users.models import RoleUser, User
from apps.customizer.models import Artwork, CustomizerPricingSettings, DesignDraft, DesignLayer, DesignerView, PrintArea
from apps.customizer.ai_models import Product3DAsset
from .models import AuditLog
from .services import (
    OrderTransitionError,
    mark_delivered,
    mark_shipped,
    start_preparing,
)

from .forms import (
    ArtworkForm,
    ContactPageSettingsForm,
    CustomizerPricingForm,
    CategoryForm,
    ProductColorForm,
    ProductImageForm,
    ProductForm,
    ProductVariantForm,
    ProductSizeForm,
    UserForm,
    OrderWorkflowActionForm,
)


class ControlAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return (
            self.request.user.is_authenticated
            and self.request.user.is_active
            and (
                self.request.user.is_superuser
                or self.request.user.is_staff
                or self.request.user.role != RoleUser.CUSTOMER
            )
        )


class RoleGuardMixin(ControlAccessMixin):
    allowed_roles = set()

    def test_func(self):
        if not super().test_func():
            return False
        return self.request.user.is_superuser or self.request.user.role in self.allowed_roles


class ShopListMixin(RoleGuardMixin):
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}


DASHBOARD_DATA_CACHE_KEY = "babaei:control:dashboard:v3"
DASHBOARD_DATA_CACHE_TTL = 20


class DashboardView(RoleGuardMixin, TemplateView):
    template_name = "control_center/dashboard.html"
    # Every non-customer role gets a landing page in the Control Center;
    # individual sections remain protected by their own role guards.
    allowed_roles = {
        RoleUser.ADMIN,
        RoleUser.STORE_MANAGER,
        RoleUser.ORDER_MANAGER,
        RoleUser.DESIGN_MANAGER,
        RoleUser.SUPPORT_MANAGER,
        RoleUser.BLOG_MANAGER,
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        cached = cache.get(DASHBOARD_DATA_CACHE_KEY)
        if cached is not None:
            context.update(cached)
            context["dashboard_updated_at"] = timezone.localtime(timezone.now())
            return context

        paid_filter = {"payment_status": Order.PaymentStatus.PAID}
        paid_orders = Order.objects.filter(**paid_filter)
        now = timezone.now()
        today = timezone.localdate()
        week_start = today - timedelta(days=6)

        daily_rows = list(
            paid_orders
            .filter(created_at__date__gte=week_start)
            .annotate(day=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
            .values("day")
            .annotate(
                orders=Count("id"),
                revenue=Sum("total_amount"),
            )
            .order_by("day")
        )
        daily_map = {row["day"]: row for row in daily_rows}

        daily_sales = []
        max_daily_revenue = 0
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            row = daily_map.get(day, {"orders": 0, "revenue": 0}) 
            revenue = row["revenue"] or 0
            max_daily_revenue = max(max_daily_revenue, revenue)
            daily_sales.append({
                "label": day.strftime("%m/%d"),
                "orders": row["orders"],
                "revenue": revenue,
            })

        current_month = today.replace(day=1)
        month_starts = []
        cursor = current_month
        for _ in range(6):
            month_starts.append(cursor)
            cursor = (cursor - timedelta(days=1)).replace(day=1)
        month_starts.reverse()

        month_rows = list(
            paid_orders
            .filter(created_at__date__gte=month_starts[0])
            .annotate(month=TruncMonth("created_at", tzinfo=timezone.get_current_timezone()))
            .values("month")
            .annotate(
                orders=Count("id"),
                revenue=Sum("total_amount"),
            )
            .order_by("month")
        )
        month_map = {
            row["month"].date().replace(day=1): row
            for row in month_rows
            if row["month"] is not None
        }

        monthly_sales = []
        max_monthly_revenue = 0
        for month in month_starts:
            row = month_map.get(month, {"orders": 0, "revenue": 0})
            revenue = row["revenue"] or 0
            max_monthly_revenue = max(max_monthly_revenue, revenue)
            monthly_sales.append({
                "label": month.strftime("%Y/%m"),
                "orders": row["orders"],
                "revenue": revenue,
            })

        max_daily_revenue = max_daily_revenue or 1
        max_monthly_revenue = max_monthly_revenue or 1
        for row in daily_sales:
            row["width"] = max(3, round(row["revenue"] * 100 / max_daily_revenue))
        for row in monthly_sales:
            row["width"] = max(3, round(row["revenue"] * 100 / max_monthly_revenue))

        top_products = list(
            paid_orders.filter(items__isnull=False)
            .values("items__product_id", "items__product_name")
            .annotate(
                quantity=Sum("items__quantity"),
                revenue=Sum("items__line_total"),
            )
            .order_by("-quantity", "-revenue")[:5]
        )
        max_top_quantity = max((row["quantity"] or 0 for row in top_products), default=0) or 1
        for row in top_products:
            row["width"] = max(8, round((row["quantity"] or 0) * 100 / max_top_quantity))

        today_revenue = paid_orders.filter(created_at__date=today).aggregate(
            revenue=Sum("total_amount")
        )["revenue"] or 0

        dashboard_data = {
            "user_count": User.objects.filter(is_active=True).count(),
            "product_count": Product.objects.filter(is_active=True).count(),
            "category_count": Category.objects.filter(is_active=True).count(),
            "order_count": Order.objects.count(),
            "paid_order_count": paid_orders.count(),
            "today_revenue": today_revenue,
            "daily_sales": daily_sales,
            "monthly_sales": monthly_sales,
            "top_products": top_products,
        }
        cache.set(DASHBOARD_DATA_CACHE_KEY, dashboard_data, DASHBOARD_DATA_CACHE_TTL)
        context.update(dashboard_data)
        context["dashboard_updated_at"] = timezone.localtime(now)
        return context


class ThreeDStudioPricingView(RoleGuardMixin, UpdateView):
    model = CustomizerPricingSettings
    form_class = CustomizerPricingForm
    template_name = "control_center/3d/pricing.html"
    success_url = reverse_lazy("control:3d_pricing")
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}

    def get_object(self, queryset=None):
        return CustomizerPricingSettings.get_solo()

    def form_valid(self, form):
        messages.success(
            self.request,
            "قیمت‌گذاری طراحی سه‌بعدی با موفقیت بروزرسانی شد.",
        )
        return super().form_valid(form)



class OrderListView(RoleGuardMixin, ListView):
    template_name = "control_center/orders/list.html"
    context_object_name = "orders"
    paginate_by = 25
    allowed_roles = {RoleUser.ADMIN, RoleUser.ORDER_MANAGER}

    def get_queryset(self):
        item_counts = (
            OrderItem.objects
            .filter(order_id=OuterRef("pk"))
            .values("order_id")
            .annotate(value=Count("id"))
            .values("value")[:1]
        )
        item_quantities = (
            OrderItem.objects
            .filter(order_id=OuterRef("pk"))
            .values("order_id")
            .annotate(value=Sum("quantity"))
            .values("value")[:1]
        )
        has_3d_design = Exists(
            OrderItem.objects.filter(
                order_id=OuterRef("pk"),
                custom_design__isnull=False,
            )
        )

        qs = (
            Order.objects
            .select_related("user")
            .only(
                "id",
                "number",
                "status",
                "payment_status",
                "shipping_status",
                "total_amount",
                "created_at",
                "user_id",
                "user__first_name",
                "user__last_name",
                "user__phone",
            )
            .annotate(
                item_count=Subquery(item_counts, output_field=IntegerField()),
                total_quantity=Subquery(item_quantities, output_field=IntegerField()),
                has_3d_design=has_3d_design,
            )
            .order_by("-created_at", "-id")
        )

        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        payment_status = self.request.GET.get("payment_status", "").strip()
        shipping_status = self.request.GET.get("shipping_status", "").strip()
        design = self.request.GET.get("design", "").strip()
        period = self.request.GET.get("period", "").strip()

        if query:
            qs = qs.filter(
                Q(number__icontains=query)
                | Q(payment_reference__icontains=query)
                | Q(shipping_phone__icontains=query)
                | Q(shipping_recipient__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
                | Q(user__phone__icontains=query)
            )

        if status in dict(Order.Status.choices):
            qs = qs.filter(status=status)
        if payment_status in dict(Order.PaymentStatus.choices):
            qs = qs.filter(payment_status=payment_status)
        if shipping_status in dict(Order.ShippingStatus.choices):
            qs = qs.filter(shipping_status=shipping_status)
        if design == "3d":
            qs = qs.filter(has_3d_design=True)
        elif design == "without_3d":
            qs = qs.filter(has_3d_design=False)

        today = timezone.localdate()
        current_tz = timezone.get_current_timezone()
        today_start = timezone.make_aware(
            datetime.combine(today, time.min),
            current_tz,
        )
        tomorrow_start = today_start + timedelta(days=1)

        if period == "today":
            qs = qs.filter(created_at__gte=today_start, created_at__lt=tomorrow_start)
        elif period == "7":
            qs = qs.filter(created_at__gte=today_start - timedelta(days=6))
        elif period == "30":
            qs = qs.filter(created_at__gte=today_start - timedelta(days=29))

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        current_tz = timezone.get_current_timezone()
        month_start = timezone.make_aware(
            datetime.combine(today.replace(day=1), time.min),
            current_tz,
        )

        stats = Order.objects.aggregate(
            total=Count("id"),
            pending_payment=Count(
                "id",
                filter=Q(
                    payment_status__in=[
                        Order.PaymentStatus.UNPAID,
                        Order.PaymentStatus.PENDING,
                    ]
                ),
            ),
            ready=Count(
                "id",
                filter=Q(
                    payment_status=Order.PaymentStatus.PAID,
                    status__in=[Order.Status.PAID, Order.Status.PROCESSING],
                ),
            ),
            shipping=Count(
                "id",
                filter=Q(shipping_status=Order.ShippingStatus.SHIPPED),
            ),
            month_revenue=Sum(
                "total_amount",
                filter=Q(
                    payment_status=Order.PaymentStatus.PAID,
                    created_at__gte=month_start,
                ),
            ),
        )

        context.update({
            "status_choices": Order.Status.choices,
            "payment_status_choices": Order.PaymentStatus.choices,
            "shipping_status_choices": Order.ShippingStatus.choices,
            "order_total_count": stats["total"] or 0,
            "order_pending_payment_count": stats["pending_payment"] or 0,
            "order_ready_count": stats["ready"] or 0,
            "order_shipping_count": stats["shipping"] or 0,
            "order_month_revenue": stats["month_revenue"] or 0,
        })
        return context


class OrderDetailView(RoleGuardMixin, TemplateView):
    template_name = "control_center/orders/detail.html"
    allowed_roles = {RoleUser.ADMIN, RoleUser.ORDER_MANAGER}

    def get_order(self):
        primary_images = ProductImage.objects.filter(
            product_id=OuterRef("product_id"),
            image_type=ProductImage.ImageType.PRIMARY,
        ).order_by("sort_order", "id")

        primary_image_url = Concat(
            Value(settings.MEDIA_URL),
            Subquery(
                primary_images.values("image")[:1],
                output_field=CharField(max_length=500),
            ),
            output_field=CharField(max_length=520),
        )

        item_qs = (
            OrderItem.objects
            .select_related(
                "product",
                "variant__color",
                "variant__size",
                "custom_design",
            )
            .annotate(primary_image_url=primary_image_url)
            .order_by("id")
        )

        return get_object_or_404(
            Order.objects
            .select_related("user")
            .prefetch_related(
                Prefetch("items", queryset=item_qs),
            ),
            pk=self.kwargs["pk"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.get_order()
        context.update({
            "order": order,
        })
        return context


class OrderWorkflowActionView(RoleGuardMixin, View):
    allowed_roles = {RoleUser.ADMIN, RoleUser.ORDER_MANAGER}

    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        form = OrderWorkflowActionForm(request.POST)

        if not form.is_valid():
            messages.error(request, "عملیات وضعیت سفارش نامعتبر است.")
            return redirect("control:order_detail", pk=order.pk)

        action = form.cleaned_data["action"]
        try:
            if action == "preparing":
                updated = start_preparing(order)
                message = "سفارش وارد مرحله آماده‌سازی شد."
            elif action == "shipped":
                updated = mark_shipped(order)
                message = "ارسال سفارش ثبت شد."
            elif action == "delivered":
                updated = mark_delivered(order)
                message = "تحویل سفارش ثبت شد."
            else:
                raise OrderTransitionError("عملیات پشتیبانی نمی‌شود.")
        except OrderTransitionError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"{updated.number}: {message}")

        return redirect("control:order_detail", pk=order.pk)


class OrderInvoiceView(RoleGuardMixin, TemplateView):
    template_name = "control_center/orders/invoice.html"
    allowed_roles = {RoleUser.ADMIN, RoleUser.ORDER_MANAGER}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item_qs = OrderItem.objects.only(
            "id",
            "order_id",
            "product_name",
            "variant_sku",
            "color_name",
            "size_name",
            "unit_price",
            "quantity",
            "line_total",
            "custom_design_code",
        ).order_by("id")

        order = get_object_or_404(
            Order.objects.only(
                "id",
                "number",
                "created_at",
                "payment_status",
                "payment_reference",
                "shipping_recipient",
                "shipping_phone",
                "shipping_title",
                "shipping_province",
                "shipping_city",
                "shipping_postal_code",
                "shipping_address",
                "subtotal",
                "discount_amount",
                "shipping_amount",
                "total_amount",
                "user_id",
            ).prefetch_related(
                Prefetch("items", queryset=item_qs)
            ),
            pk=self.kwargs["pk"],
        )
        context["order"] = order
        return context


class ArtworkLibraryListView(ShopListMixin, ListView):
    model = Artwork
    template_name = "control_center/3d/library.html"
    context_object_name = "library"
    paginate_by = 24
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}

    def get_queryset(self):
        return (
            Artwork.objects
            .filter(source=Artwork.Source.LIBRARY)
            .annotate(
                confirmed_usage_count=Count(
                    "design_layers",
                    filter=Q(
                        design_layers__draft__status=DesignDraft.Status.CONFIRMED,
                        design_layers__draft__order_items__order__payment_status=Order.PaymentStatus.PAID,
                    ),
                ),
                has_design_layers=Exists(
                    DesignLayer.objects.filter(artwork_id=OuterRef("pk"))
                ),
            )
            .order_by("-created_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base = Artwork.objects.filter(source=Artwork.Source.LIBRARY)
        library_stats = base.aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(is_active=True)),
            inactive=Count("id", filter=Q(is_active=False)),
        )
        context.update({
            "library_count": library_stats["total"] or 0,
            "library_active_count": library_stats["active"] or 0,
            "library_inactive_count": library_stats["inactive"] or 0,
        })
        return context


class CustomerArtworkListView(ShopListMixin, ListView):
    model = Artwork
    template_name = "control_center/3d/customer_artworks.html"
    context_object_name = "customer_artworks"
    paginate_by = 24
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}

    def get_queryset(self):
        registered_filter = Q(
            design_layers__draft__status=DesignDraft.Status.CONFIRMED,
            design_layers__draft__order_items__isnull=False,
            design_layers__draft__order_items__order__payment_status=Order.PaymentStatus.PAID,
        )
        latest_order_items = OrderItem.objects.filter(
            custom_design__status=DesignDraft.Status.CONFIRMED,
            order__payment_status=Order.PaymentStatus.PAID,
            custom_design__layers__artwork=OuterRef("pk"),
        ).order_by("-order__paid_at", "-order__created_at", "-id")
        return (
            Artwork.objects
            .filter(source=Artwork.Source.UPLOAD)
            .filter(registered_filter)
            .distinct()
            .select_related("owner")
            .annotate(
                confirmed_usage_count=Count(
                    "design_layers",
                    filter=registered_filter,
                    distinct=True,
                ),
                order_count=Count(
                    "design_layers__draft__order_items__order",
                    filter=registered_filter,
                    distinct=True,
                ),
                latest_order_id=Subquery(latest_order_items.values("order_id")[:1]),
                latest_order_created_at=Subquery(latest_order_items.values("order__created_at")[:1]),
                latest_order_number=Subquery(latest_order_items.values("order__number")[:1]),
                latest_product_name=Subquery(latest_order_items.values("product_name")[:1]),
                latest_color_name=Subquery(latest_order_items.values("color_name")[:1]),
                latest_size_name=Subquery(latest_order_items.values("size_name")[:1]),
                latest_design_uuid=Subquery(latest_order_items.values("custom_design__uuid")[:1]),
                latest_design_code=Subquery(latest_order_items.values("custom_design_code")[:1]),
            )
            .order_by("-created_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        registered = Artwork.objects.filter(
            source=Artwork.Source.UPLOAD,
            design_layers__draft__status=DesignDraft.Status.CONFIRMED,
            design_layers__draft__order_items__isnull=False,
            design_layers__draft__order_items__order__payment_status=Order.PaymentStatus.PAID,
        ).distinct()
        context["customer_artwork_count"] = registered.count()
        context["customer_artwork_order_count"] = OrderItem.objects.filter(
            custom_design__status=DesignDraft.Status.CONFIRMED,
            order__payment_status=Order.PaymentStatus.PAID,
            custom_design__layers__artwork__source=Artwork.Source.UPLOAD,
        ).values("order_id").distinct().count()
        return context

class ArtworkCreateView(ShopListMixin, CreateView):
    model = Artwork
    form_class = ArtworkForm
    template_name = "control_center/3d/artwork_form.html"
    success_url = reverse_lazy("control:artwork_library")
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}

    def form_valid(self, form):
        form.instance.source = Artwork.Source.LIBRARY
        form.instance.processing_status = Artwork.ProcessingStatus.READY
        form.instance.background_removed = True
        form.instance.owner = None
        form.instance.session_key = ""
        messages.success(self.request, "لیبل با موفقیت به کتابخانه اضافه شد.")
        return super().form_valid(form)


class ArtworkUpdateView(ShopListMixin, UpdateView):
    model = Artwork
    form_class = ArtworkForm
    template_name = "control_center/3d/artwork_form.html"
    success_url = reverse_lazy("control:artwork_library")
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}

    def get_queryset(self):
        return Artwork.objects.filter(source=Artwork.Source.LIBRARY)

    def form_valid(self, form):
        form.instance.source = Artwork.Source.LIBRARY
        form.instance.owner = None
        form.instance.session_key = ""
        messages.success(self.request, "اطلاعات لیبل بروزرسانی شد.")
        return super().form_valid(form)


class ArtworkDeleteView(ShopListMixin, View):
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}

    def post(self, request, pk):
        artwork = get_object_or_404(
            Artwork,
            pk=pk,
            source=Artwork.Source.LIBRARY,
        )
        if DesignLayer.objects.filter(artwork=artwork).exists():
            messages.error(
                request,
                "این لیبل قبلاً در طراحی استفاده شده و قابل حذف نیست؛ آن را غیرفعال کن.",
            )
            return redirect("control:artwork_library")

        if artwork.area_prices.exists():
            messages.error(
                request,
                "این لیبل دارای قیمت‌گذاری ناحیه چاپ است و قابل حذف نیست؛ آن را غیرفعال کن.",
            )
            return redirect("control:artwork_library")

        artwork.delete()
        messages.success(request, "لیبل از کتابخانه حذف شد.")
        return redirect("control:artwork_library")


class ThreeDStudioDashboardView(ShopListMixin, TemplateView):
    template_name = "control_center/3d/dashboard.html"
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        library = Artwork.objects.filter(
            source=Artwork.Source.LIBRARY
        ).order_by("-created_at")
        library_preview = list(library[:4])

        registered_customer_labels = Artwork.objects.filter(
            source=Artwork.Source.UPLOAD,
            design_layers__draft__status=DesignDraft.Status.CONFIRMED,
            design_layers__draft__order_items__isnull=False,
            design_layers__draft__order_items__order__payment_status=Order.PaymentStatus.PAID,
        ).distinct()
        customer_label_preview = list(
            registered_customer_labels.order_by("-created_at")[:4]
        )

        purchased_design_base = (
            OrderItem.objects.filter(
                custom_design__status=DesignDraft.Status.CONFIRMED,
                order__payment_status=Order.PaymentStatus.PAID,
            )
            .select_related(
                "order",
                "product",
                "variant__color",
                "variant__size",
                "custom_design",
            )
            .prefetch_related(
                Prefetch(
                    "custom_design__layers",
                    queryset=DesignLayer.objects.filter(
                        layer_type=DesignLayer.LayerType.ARTWORK,
                    ),
                )
            )
            .annotate(
                label_count=Count(
                    "custom_design__layers",
                    filter=Q(
                        custom_design__layers__layer_type=DesignLayer.LayerType.ARTWORK,
                    ),
                    distinct=True,
                )
            )
            .order_by("-order__paid_at", "-order__created_at", "-id")
        )

        pending_qs = purchased_design_base.filter(
            custom_design__production_completed_at__isnull=True
        )
        completed_qs = purchased_design_base.filter(
            custom_design__production_completed_at__isnull=False
        )

        pending_designs = list(pending_qs[:20])
        completed_designs = list(completed_qs[:20])

        for item in pending_designs + completed_designs:
            item.design_display_color = item.color_name or item.custom_design.shirt_color or ""
            item.design_display_size = item.size_name or ""
            item.design_layer_count = item.label_count or 0

        pending_design_total_count = pending_qs.count()
        completed_design_total_count = completed_qs.count()

        # Keep the complete purchased-design collection available for
        # templates and compatibility with earlier dashboard markup.
        purchased_design_items = pending_designs + completed_designs

        pricing_settings = CustomizerPricingSettings.get_solo()
        context.update({
            "pricing_tshirt_base": pricing_settings.tshirt_base_price,
            "pricing_customer_label": pricing_settings.customer_label_price,
            "library_count": library.count(),
            "library_preview": library_preview,
            "customer_artwork_count": registered_customer_labels.count(),
            "customer_artwork_preview": customer_label_preview,
            "customer_artwork_order_count": OrderItem.objects.filter(
                custom_design__status=DesignDraft.Status.CONFIRMED,
                order__payment_status=Order.PaymentStatus.PAID,
                custom_design__layers__artwork__source=Artwork.Source.UPLOAD,
            ).values("order_id").distinct().count(),
            "ordered_design_count": OrderItem.objects.filter(
                custom_design__status=DesignDraft.Status.CONFIRMED,
                order__payment_status=Order.PaymentStatus.PAID,
            ).values("custom_design_id").distinct().count(),
            "ready_3d_count": Product3DAsset.objects.filter(
                status=Product3DAsset.Status.READY
            ).count(),
            "purchased_designs": purchased_design_items,
            "pending_designs": pending_designs,
            "completed_designs": completed_designs,
            "pending_design_count": len(pending_designs),
            "completed_design_count": len(completed_designs),
            "completed_design_total_count": completed_design_total_count,
            "pending_design_total_count": pending_design_total_count,
        })
        return context


class ThreeDProductionCompletionView(ShopListMixin, View):
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}

    def post(self, request, uuid):
        design = get_object_or_404(
            DesignDraft,
            uuid=uuid,
            status=DesignDraft.Status.CONFIRMED,
            order_items__order__payment_status=Order.PaymentStatus.PAID,
        )
        if design.production_completed_at:
            design.production_completed_at = None
            message = "طراحی دوباره به سفارش‌های انجام‌نشده برگشت."
        else:
            design.production_completed_at = timezone.now()
            message = "طراحی به سفارش‌های تمام‌شده منتقل شد."

        design.save(update_fields=["production_completed_at", "updated_at"])
        messages.success(request, message)
        return redirect("control:3d_dashboard")

class PurchasedDesignDetailView(ShopListMixin, TemplateView):
    template_name = "control_center/3d/design_detail.html"
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}

    def get_design(self):
        layer_qs = (
            DesignLayer.objects
            .select_related("artwork", "area")
            .order_by("side", "z_index", "id")
        )
        order_item_qs = (
            OrderItem.objects
            .filter(order__payment_status=Order.PaymentStatus.PAID)
            .select_related(
                "order",
                "product",
                "variant__color",
                "variant__size",
            )
            .order_by("-order__paid_at", "-order__created_at", "-id")
        )
        return get_object_or_404(
            DesignDraft.objects
            .filter(
                uuid=self.kwargs["uuid"],
                status=DesignDraft.Status.CONFIRMED,
                order_items__order__payment_status=Order.PaymentStatus.PAID,
            )
            .distinct()
            .select_related(
                "product",
                "variant__color",
                "variant__size",
                "user",
            )
            .prefetch_related(
                Prefetch("layers", queryset=layer_qs, to_attr="detail_layers"),
                Prefetch("order_items", queryset=order_item_qs, to_attr="purchased_order_items"),
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        design = self.get_design()
        purchase_item = design.purchased_order_items[0] if design.purchased_order_items else None

        front_layers = []
        back_layers = []
        for layer in getattr(design, "detail_layers", []):
            if layer.layer_type not in {
                DesignLayer.LayerType.ARTWORK,
                DesignLayer.LayerType.TEXT,
            }:
                continue

            layer.is_text_layer = layer.layer_type == DesignLayer.LayerType.TEXT
            layer.display_text = layer.text if layer.is_text_layer else ""
            layer.text_style_data = layer.text_style or {}
            layer.text_font_family = str(
                layer.text_style_data.get("fontFamily")
                or "Arial, Tahoma, sans-serif"
            )
            layer.text_font_weight = int(layer.text_style_data.get("fontWeight") or 700)
            layer.text_font_style = (
                "italic"
                if layer.text_style_data.get("fontStyle") == "italic"
                else "normal"
            )
            layer.text_letter_spacing = float(
                layer.text_style_data.get("letterSpacing") or 0
            )
            layer.text_font_size = float(
                layer.text_style_data.get("fontSize") or 100
            )

            layer.overlay_style = (
                f"left:{layer.x * 100:.2f}%;"
                f"top:{layer.y * 100:.2f}%;"
                f"width:{layer.width * 100:.2f}%;"
                f"height:{layer.height * 100:.2f}%;"
                f"transform:translate(-50%,-50%) rotate({layer.rotation:.2f}deg);"
            )
            layer.position_summary = f"X {layer.x * 100:.2f}% · Y {layer.y * 100:.2f}%"
            layer.size_summary = f"{layer.width * 100:.2f}% × {layer.height * 100:.2f}%"

            if layer.side == DesignLayer.Side.BACK:
                back_layers.append(layer)
            else:
                front_layers.append(layer)

        label_layers = [
            layer
            for layer in front_layers + back_layers
            if not layer.is_text_layer
        ]
        text_layers = [
            layer
            for layer in front_layers + back_layers
            if layer.is_text_layer
        ]

        context.update({
            "design": design,
            "purchase_item": purchase_item,
            "front_layers": front_layers,
            "back_layers": back_layers,
            "label_layers": label_layers,
            "text_layers": text_layers,
            "front_label_count": sum(1 for layer in front_layers if not layer.is_text_layer),
            "back_label_count": sum(1 for layer in back_layers if not layer.is_text_layer),
            "label_count": len(label_layers),
            "text_count": len(text_layers),
            "layer_count": len(front_layers) + len(back_layers),
        })
        return context

class PurchasedDesignTextDownloadView(ShopListMixin, View):
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}

    def get(self, request, uuid, layer_id):
        layer = get_object_or_404(
            DesignLayer.objects.select_related("draft"),
            pk=layer_id,
            draft__uuid=uuid,
            draft__status=DesignDraft.Status.CONFIRMED,
            draft__order_items__order__payment_status=Order.PaymentStatus.PAID,
            layer_type=DesignLayer.LayerType.TEXT,
        )

        text_value = str(layer.text or "").strip()
        if not text_value:
            raise Http404

        style = layer.text_style if isinstance(layer.text_style, dict) else {}
        font_family = str(
            style.get("fontFamily") or "Arial, Tahoma, sans-serif"
        )
        font_weight = int(style.get("fontWeight") or 700)
        font_style = (
            "italic" if style.get("fontStyle") == "italic" else "normal"
        )
        font_size = max(60, min(160, float(style.get("fontSize") or 100)))
        curve = max(-80, min(80, float(style.get("curve") or 0)))
        letter_spacing = max(-2, min(12, float(style.get("letterSpacing") or 0)))

        safe_text = html.escape(text_value)
        safe_font = html.escape(font_family, quote=True)
        safe_color = str(style.get("color") or "#111111")
        if not safe_color.startswith("#"):
            safe_color = "#111111"

        # Transparent SVG: no background rectangle is created.
        # The text is kept as vector text and follows the same curved path
        # used by the 3D customizer when a curve is configured.
        width = 1200
        height = 520
        font_px = max(36, 110 * (font_size / 100.0))
        control_y = 290 - (curve * 1.8)

        if abs(curve) > 0.01:
            text_markup = (
                '<defs>'
                '<path id="babaei-text-path" d="M 100 280 '
                f'Q 600 {control_y:.2f} 1100 280"/>'
                '</defs>'
                f'<text fill="{safe_color}" font-family="{safe_font}" '
                f'font-size="{font_px:.2f}px" font-weight="{font_weight}" '
                f'font-style="{font_style}" letter-spacing="{letter_spacing:.2f}px">'
                '<textPath href="#babaei-text-path" startOffset="50%" '
                f'text-anchor="middle">{safe_text}</textPath></text>'
            )
        else:
            text_markup = (
                f'<text x="600" y="280" text-anchor="middle" '
                f'dominant-baseline="middle" fill="#ffffff" '
                f'font-family="{safe_font}" font-size="{font_px:.2f}px" '
                f'font-weight="{font_weight}" font-style="{font_style}" '
                f'letter-spacing="{letter_spacing:.2f}px">{safe_text}</text>'
            )

        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
     viewBox="0 0 {width} {height}" style="background:transparent" fill="none">
  {text_markup}
</svg>
'''

        response = HttpResponse(svg, content_type="image/svg+xml; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="text-{layer.id}.svg"'
        )
        return response

class PurchasedDesignArtworkDownloadView(ShopListMixin, View):
    allowed_roles = {RoleUser.ADMIN, RoleUser.STORE_MANAGER}

    def get(self, request, uuid, artwork_id):
        layer_exists = DesignLayer.objects.filter(
            draft__uuid=uuid,
            draft__status=DesignDraft.Status.CONFIRMED,
            artwork_id=artwork_id,
            draft__order_items__order__payment_status=Order.PaymentStatus.PAID,
            layer_type=DesignLayer.LayerType.ARTWORK,
        ).exists()
        if not layer_exists:
            raise Http404

        artwork = get_object_or_404(Artwork, pk=artwork_id)
        if not artwork.image:
            raise Http404

        try:
            file_handle = artwork.image.open("rb")
        except (OSError, ValueError, FileNotFoundError) as exc:
            raise Http404 from exc

        content_type = mimetypes.guess_type(artwork.image.name)[0] or "application/octet-stream"
        suffix = ""
        if "." in artwork.image.name.rsplit("/", 1)[-1]:
            suffix = "." + artwork.image.name.rsplit(".", 1)[-1].lower()

        response = FileResponse(
            file_handle,
            as_attachment=True,
            filename=f"{artwork.code}{suffix or '.png'}",
        )
        response["Content-Type"] = content_type
        return response
class AuditLogListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    template_name = "control_center/reports/list.html"
    context_object_name = "audit_logs"
    paginate_by = 30

    def test_func(self):
        return (
            self.request.user.is_authenticated
            and self.request.user.is_active
            and self.request.user.is_superuser
        )

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor").order_by("-created_at")

        query = self.request.GET.get("q", "").strip()
        action = self.request.GET.get("action", "").strip()
        method = self.request.GET.get("method", "").strip().upper()
        result = self.request.GET.get("result", "").strip()
        period = self.request.GET.get("period", "").strip()
        user_id = self.request.GET.get("user", "").strip()

        if query:
            qs = qs.filter(
                Q(description__icontains=query)
                | Q(path__icontains=query)
                | Q(actor__first_name__icontains=query)
                | Q(actor__last_name__icontains=query)
                | Q(actor__phone__icontains=query)
                | Q(ip_address__icontains=query)
            )

        valid_actions = {label for _, label in self._action_choices()}
        if action in valid_actions:
            qs = qs.filter(action=action)

        if method in dict(AuditLog.Method.choices):
            qs = qs.filter(method=method)

        if result in dict(AuditLog.Result.choices):
            qs = qs.filter(result=result)

        if user_id.isdigit():
            qs = qs.filter(actor_id=int(user_id))

        today = timezone.localdate()
        current_tz = timezone.get_current_timezone()
        today_start = timezone.make_aware(datetime.combine(today, time.min), current_tz)
        if period == "today":
            qs = qs.filter(created_at__gte=today_start, created_at__lt=today_start + timedelta(days=1))
        elif period == "7":
            qs = qs.filter(created_at__gte=today_start - timedelta(days=6))
        elif period == "30":
            qs = qs.filter(created_at__gte=today_start - timedelta(days=29))

        return qs

    @staticmethod
    def _action_choices():
        from .middleware import ACTION_LABELS
        return sorted(ACTION_LABELS.items(), key=lambda item: item[1])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        today_start = timezone.make_aware(
            datetime.combine(today, time.min),
            timezone.get_current_timezone(),
        )
        context.update({
            "action_choices": [(label, label) for _, label in self._action_choices()],
            "method_choices": AuditLog.Method.choices,
            "result_choices": AuditLog.Result.choices,
            "report_total_count": AuditLog.objects.count(),
            "report_today_count": AuditLog.objects.filter(
                created_at__gte=today_start,
                created_at__lt=today_start + timedelta(days=1),
            ).count(),
            "report_error_count": AuditLog.objects.filter(status_code__gte=400).count(),
            "report_user_count": AuditLog.objects.filter(
                actor_id__isnull=False,
            ).values("actor_id").distinct().count(),
            "report_users": User.objects.filter(
                is_active=True,
            ).only(
                "id", "first_name", "last_name", "phone", "role",
            ).order_by("first_name", "last_name", "phone")[:100],
        })
        return context


class ContactPageSettingsView(RoleGuardMixin, UpdateView):
    model = ContactPageSettings
    form_class = ContactPageSettingsForm
    template_name = "control_center/contact/form.html"
    success_url = reverse_lazy("control:contact_settings")
    allowed_roles = {RoleUser.ADMIN}

    def get_object(self, queryset=None):
        return ContactPageSettings.get_solo()

    def form_valid(self, form):
        messages.success(self.request, "اطلاعات صفحه تماس با ما با موفقیت ذخیره شد.")
        return super().form_valid(form)


class CommentListView(RoleGuardMixin, ListView):
    template_name = "control_center/comments/list.html"
    context_object_name = "comments"
    paginate_by = 20
    allowed_roles = {RoleUser.ADMIN, RoleUser.SUPPORT_MANAGER}

    def test_func(self):
        if (
            self.request.user.is_authenticated
            and self.request.user.is_active
            and self.request.user.is_staff
            and self.request.user.role == RoleUser.CUSTOMER
        ):
            return True
        return super().test_func()

    def get_queryset(self):
        qs = (
            ProductComment.objects
            .select_related("product", "user")
            .order_by("-created_at", "-id")
        )

        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        rating = self.request.GET.get("rating", "").strip()

        if query:
            qs = qs.filter(
                Q(body__icontains=query)
                | Q(product__name__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
                | Q(user__phone__icontains=query)
            )

        if status in dict(ProductComment.Status.choices):
            qs = qs.filter(status=status)

        if rating in {"1", "2", "3", "4", "5"}:
            qs = qs.filter(rating=int(rating))

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = ProductComment.Status.choices
        context["stats"] = ProductComment.objects.aggregate(
            total=Count("id"),
            pending=Count("id", filter=Q(status=ProductComment.Status.PENDING)),
            approved=Count("id", filter=Q(status=ProductComment.Status.APPROVED)),
            rejected=Count("id", filter=Q(status=ProductComment.Status.REJECTED)),
        )
        return context


class CommentModerationView(RoleGuardMixin, View):
    allowed_roles = {RoleUser.ADMIN, RoleUser.SUPPORT_MANAGER}

    def test_func(self):
        if (
            self.request.user.is_authenticated
            and self.request.user.is_active
            and self.request.user.is_staff
            and self.request.user.role == RoleUser.CUSTOMER
        ):
            return True
        return super().test_func()

    def post(self, request, pk, action):
        comment = get_object_or_404(ProductComment, pk=pk)

        if action == "approve":
            comment.status = ProductComment.Status.APPROVED
            message = "نظر با موفقیت تأیید شد."
        elif action == "reject":
            comment.status = ProductComment.Status.REJECTED
            message = "نظر با موفقیت رد شد."
        else:
            raise Http404

        comment.save(update_fields=("status", "updated_at"))
        messages.success(request, message)
        return redirect(request.POST.get("next") or "control:comments")


class UserListView(RoleGuardMixin, ListView):
    template_name = "control_center/users/list.html"
    context_object_name = "users"
    paginate_by = 25
    allowed_roles = {RoleUser.ADMIN, RoleUser.SUPPORT_MANAGER}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["roles"] = User._meta.get_field("role").choices
        return context

    def get_queryset(self):
        # The technical superuser is managed exclusively through Django
        # admin and must never appear in the operational Control Center.
        qs = User.objects.filter(
            is_superuser=False,
        ).only(
            "id", "first_name", "last_name", "phone", "email",
            "role", "image", "is_active", "date_joined",
        ).order_by("-date_joined")
        q = self.request.GET.get("q", "").strip()
        role = self.request.GET.get("role", "").strip()
        if q:
            qs = qs.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(email__icontains=q)
            )
        if role in dict(RoleUser.choices):
            qs = qs.filter(role=role)
        return qs


class UserCreateView(RoleGuardMixin, CreateView):
    form_class = UserForm
    template_name = "control_center/users/form.html"
    success_url = reverse_lazy("control:users")
    allowed_roles = {RoleUser.ADMIN}

    def form_valid(self, form):
        messages.success(self.request, "کاربر با موفقیت ایجاد شد.")
        return super().form_valid(form)


class UserUpdateView(RoleGuardMixin, UpdateView):
    model = User
    form_class = UserForm
    template_name = "control_center/users/form.html"
    success_url = reverse_lazy("control:users")
    allowed_roles = {RoleUser.ADMIN}

    def get_queryset(self):
        return User.objects.filter(is_superuser=False)

    def form_valid(self, form):
        messages.success(self.request, "اطلاعات کاربر بروزرسانی شد.")
        return super().form_valid(form)


class UserDeleteView(RoleGuardMixin, DeleteView):
    model = User
    template_name = "control_center/confirm_delete.html"
    success_url = reverse_lazy("control:users")
    allowed_roles = {RoleUser.ADMIN}

    def get_queryset(self):
        return User.objects.filter(is_superuser=False)


class CatalogAttributeListView(ShopListMixin, TemplateView):
    template_name = "control_center/catalog/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        colors_qs = ProductColor.objects.filter(
            product__isnull=True,
        ).only("id", "name", "hex_code", "is_active").order_by("name")
        sizes_qs = ProductSize.objects.only(
            "id", "name", "slug", "sort_order", "is_active"
        ).order_by("sort_order", "name")

        colors_page = Paginator(colors_qs, 20).get_page(
            self.request.GET.get("color_page", 1)
        )
        sizes_page = Paginator(sizes_qs, 20).get_page(
            self.request.GET.get("size_page", 1)
        )

        context.update({
            "colors": colors_page.object_list,
            "sizes": sizes_page.object_list,
            "colors_page": colors_page,
            "sizes_page": sizes_page,
        })
        return context


class ProductColorCreateView(ShopListMixin, CreateView):
    model = ProductColor
    form_class = ProductColorForm
    template_name = "control_center/catalog/color_form.html"
    success_url = reverse_lazy("control:catalog")

    def form_valid(self, form):
        form.instance.product = None
        messages.success(self.request, "رنگ با موفقیت به کاتالوگ اضافه شد.")
        return super().form_valid(form)


class ProductColorUpdateView(ShopListMixin, UpdateView):
    model = ProductColor
    form_class = ProductColorForm
    template_name = "control_center/catalog/color_form.html"
    success_url = reverse_lazy("control:catalog")

    def get_queryset(self):
        return ProductColor.objects.filter(product__isnull=True)


class ProductColorDeleteView(ShopListMixin, DeleteView):
    model = ProductColor
    template_name = "control_center/confirm_delete.html"
    success_url = reverse_lazy("control:catalog")

    def get_queryset(self):
        return ProductColor.objects.filter(product__isnull=True)


class ProductSizeCreateView(ShopListMixin, CreateView):
    model = ProductSize
    form_class = ProductSizeForm
    template_name = "control_center/catalog/size_form.html"
    success_url = reverse_lazy("control:catalog")

    def form_valid(self, form):
        messages.success(self.request, "سایز با موفقیت به کاتالوگ اضافه شد.")
        return super().form_valid(form)


class ProductSizeUpdateView(ShopListMixin, UpdateView):
    model = ProductSize
    form_class = ProductSizeForm
    template_name = "control_center/catalog/size_form.html"
    success_url = reverse_lazy("control:catalog")


class ProductSizeDeleteView(ShopListMixin, DeleteView):
    model = ProductSize
    template_name = "control_center/confirm_delete.html"
    success_url = reverse_lazy("control:catalog")


class ProductListView(ShopListMixin, ListView):
    template_name = "control_center/products/list.html"
    context_object_name = "products"
    paginate_by = 25

    def get_queryset(self):
        qs = Product.objects.select_related("category")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q) | Q(slug__icontains=q)
            )

        variants = ProductVariant.objects.filter(
            product_id=OuterRef("pk")
        )
        effective_price = Case(
            When(use_product_price=True, then=OuterRef("base_price")),
            default=F("price"),
            output_field=IntegerField(),
        )

        min_price = (
            variants.annotate(_effective_price=effective_price)
            .order_by("_effective_price", "id")
            .values("_effective_price")[:1]
        )
        stock_total = (
            variants.values("product_id")
            .annotate(value=Sum("stock_quantity"))
            .values("value")[:1]
        )
        variant_total = (
            variants.values("product_id")
            .annotate(value=Count("id"))
            .values("value")[:1]
        )

        return qs.only(
            "id", "name", "slug", "base_price", "is_active",
            "category_id", "category__name", "created_at",
        ).annotate(
            min_price=Subquery(min_price, output_field=IntegerField()),
            stock=Subquery(stock_total, output_field=IntegerField()),
            variant_count=Subquery(variant_total, output_field=IntegerField()),
        ).order_by("-created_at", "-id")

ProductColorFormSet = inlineformset_factory(
    Product,
    ProductColor,
    form=ProductColorForm,
    extra=1,
    can_delete=True,
)

ProductImageFormSet = inlineformset_factory(
    Product,
    ProductImage,
    form=ProductImageForm,
    extra=1,
    can_delete=True,
)

ProductVariantFormSet = inlineformset_factory(
    Product,
    ProductVariant,
    form=ProductVariantForm,
    extra=1,
    can_delete=True,
)


DEFAULT_PRODUCT_SIZES = (
    ("S", "s", 1),
    ("M", "m", 2),
    ("L", "l", 3),
    ("XL", "xl", 4),
)


class ProductFormsetMixin:
    def _product_for_formsets(self):
        return getattr(self, "object", None) or Product()

    def get_product_formsets(self, product=None, data=None, files=None):
        product = product or self._product_for_formsets()
        common = {"instance": product, "data": data, "files": files}
        return {
            "image_formset": ProductImageFormSet(prefix="images", **common),
            "variant_formset": ProductVariantFormSet(
                prefix="variants",
                form_kwargs={"product": product if product.pk else None},
                **common,
            ),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self._product_for_formsets()
        data = self.request.POST or None
        files = self.request.FILES or None
        # Default sizes are seeded once by a data migration. Opening a product
        # form must not perform four update_or_create writes on every request.
        context.update(self.get_product_formsets(product, data=data, files=files))
        context["product_sizes"] = ProductSize.objects.filter(
            is_active=True
        ).order_by("sort_order", "name")
        color_filter = Q(product__isnull=True)
        if product.pk:
            color_filter |= Q(product=product)
        context["catalog_colors"] = ProductColor.objects.filter(
            color_filter,
            is_active=True,
        ).distinct().order_by("name")
        return context

    def _validate_and_save_formsets(self, product):
        data = self.request.POST
        files = self.request.FILES

        image_formset = ProductImageFormSet(
            data=data,
            files=files,
            instance=product,
            prefix="images",
        )

        primary_images = [
            form for form in image_formset.forms
            if not form.cleaned_data.get("DELETE")
            and form.cleaned_data.get("image_type") == ProductImage.ImageType.PRIMARY
        ]
        if len(primary_images) > 1:
            for image_form in primary_images:
                image_form.add_error("image_type", "فقط یک تصویر می‌تواند تصویر اصلی محصول باشد.")
            return None

        variant_data = data.copy()

        variant_formset = ProductVariantFormSet(
            data=variant_data,
            instance=product,
            prefix="variants",
            form_kwargs={"product": product},
        )
        if not variant_formset.is_valid():
            return None

        image_formset.save()
        variant_formset.save()
        return True


class ProductCreateView(ShopListMixin, ProductFormsetMixin, CreateView):
    form_class = ProductForm
    template_name = "control_center/products/form.html"
    success_url = reverse_lazy("control:products")

    @transaction.atomic
    def form_valid(self, form):
        self.object = form.save()
        if not self._validate_and_save_formsets(self.object):
            return self.render_to_response(self.get_context_data(form=form))
        messages.success(self.request, "محصول، رنگ‌ها، تصاویر و تنوع‌ها با موفقیت ایجاد شدند.")
        return super().form_valid(form)

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class ProductUpdateView(ShopListMixin, ProductFormsetMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = "control_center/products/form.html"
    success_url = reverse_lazy("control:products")

    @transaction.atomic
    def form_valid(self, form):
        self.object = form.save()
        if not self._validate_and_save_formsets(self.object):
            return self.render_to_response(self.get_context_data(form=form))
        messages.success(self.request, "محصول، رنگ‌ها، تصاویر و تنوع‌ها با موفقیت بروزرسانی شدند.")
        return super().form_valid(form)

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class ProductDeleteView(ShopListMixin, DeleteView):
    model = Product
    template_name = "control_center/confirm_delete.html"
    success_url = reverse_lazy("control:products")

    def form_valid(self, form):
        # DeleteView performs the actual delete from form_valid(), not
        # delete(). Catch PROTECT here so referenced products never return 500.
        self.object = self.get_object()
        try:
            self.object.delete()
        except ProtectedError:
            product_name = self.object.name
            self.object.is_active = False
            self.object.save(update_fields=("is_active", "updated_at"))
            messages.warning(
                self.request,
                f'محصول «{product_name}» سابقه استفاده دارد و قابل حذف کامل نیست؛ '
                "به‌جای حذف، غیرفعال شد تا اطلاعات سفارش‌ها حفظ شود.",
            )
        else:
            messages.success(self.request, "محصول با موفقیت حذف شد.")

        return redirect(self.success_url)

class CategoryListView(ShopListMixin, ListView):
    template_name = "control_center/categories/list.html"
    context_object_name = "categories"
    paginate_by = 30

    def get_queryset(self):
        return (
            Category.objects
            .only("id", "name", "slug", "is_active", "sort_order")
            .annotate(product_count=Count("products"))
            .order_by("sort_order", "name", "id")
        )

class CategoryCreateView(ShopListMixin, CreateView):
    form_class = CategoryForm
    template_name = "control_center/categories/form.html"
    success_url = reverse_lazy("control:categories")

class CategoryUpdateView(ShopListMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = "control_center/categories/form.html"
    success_url = reverse_lazy("control:categories")

class CategoryDeleteView(ShopListMixin, DeleteView):
    model = Category
    template_name = "control_center/confirm_delete.html"
    success_url = reverse_lazy("control:categories")
