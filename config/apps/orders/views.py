from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Case, CharField, Count, ExpressionWrapper, F, OuterRef, PositiveBigIntegerField, Prefetch, Subquery, Sum, When, Value
from django.db.models.functions import Concat
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.shop.models import Product, ProductImage, ProductVariant
from apps.marketplace.models import VendorProduct, Vendor

from apps.users.models import Address
from apps.customizer.models import DesignDraft
from apps.customizer.services import save_design_draft, save_design_preview_to_temp

from .models import Cart, CartItem, Order, OrderItem
from .services import (
    CART_COUNT_SESSION_KEY,
    CART_SESSION_KEY,
    add_to_cart,
    add_design_to_cart,
    clear_cart,
    create_order_from_cart,
    get_active_cart,
    invalidate_product_cart_cache,
    process_manual_payment,
    remove_cart_item,
    update_cart_item,
)

AUTH_USER_SESSION_KEY = "_auth_user_id"


def _is_json_request(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")


def _remember_cart_count(request, count):
    count = int(count or 0)
    if request.session.get(CART_COUNT_SESSION_KEY) != count:
        request.session[CART_COUNT_SESSION_KEY] = count
    request._babaei_cart_item_count = count
    return count


def _cart_totals(cart, request=None):
    unit_price = Case(When(custom_design__isnull=False, then=F("custom_design__total_price")), When(variant__isnull=False, then=F("variant__price")), default=F("product__base_price"), output_field=PositiveBigIntegerField())
    line_total = ExpressionWrapper(F("quantity") * unit_price, output_field=PositiveBigIntegerField())
    totals = cart.items.aggregate(count=Sum("quantity", default=0), subtotal=Sum(line_total, default=0))
    count = _remember_cart_count(request, totals["count"] or 0) if request is not None else totals["count"] or 0
    return {"count": count, "subtotal": totals["subtotal"] or 0}


def _cart_items_queryset(request):
    primary_images = ProductImage.objects.filter(
        product_id=OuterRef("product_id"),
        image_type=ProductImage.ImageType.PRIMARY,
    ).order_by("sort_order", "id")
    primary_image_url = Concat(
        Value(settings.MEDIA_URL),
        Subquery(primary_images.values("image")[:1], output_field=CharField(max_length=500)),
        output_field=CharField(max_length=520),
    )
    primary_image_alt = Subquery(
        primary_images.values("alt_text")[:1],
        output_field=CharField(max_length=180),
    )
    queryset = (
        CartItem.objects
        .select_related("cart", "product__category", "variant__color", "variant__size", "custom_design")
        .annotate(primary_image_url=primary_image_url, primary_image_alt=primary_image_alt)
    )
    user_id = request.session.get(AUTH_USER_SESSION_KEY)
    if user_id:
        return queryset.filter(cart__user_id=user_id, cart__status=Cart.Status.ACTIVE).order_by("added_at", "id")
    session_key = request.session.get(CART_SESSION_KEY) or request.session.session_key
    if not session_key:
        return queryset.none()
    return queryset.filter(cart__session_key=session_key, cart__user__isnull=True, cart__status=Cart.Status.ACTIVE).order_by("added_at", "id")


def cart_view(request):
    items = list(_cart_items_queryset(request))
    item_count = sum(item.quantity for item in items)
    subtotal = sum(item.line_total for item in items)
    _remember_cart_count(request, item_count)
    cart = items[0].cart if items else None
    hero_product = items[0].product if items else None
    return render(request, "orders/cart.html", {"cart": cart, "items": items, "item_count": item_count, "subtotal": subtotal, "hero_product": hero_product})


@require_POST
def custom_design_cart_add_view(request, slug):
    product = get_object_or_404(Product.objects.select_related("category"), slug=slug, is_active=True, category__is_active=True)
    try:
        import json
        if request.content_type.startswith("multipart/form-data"):
            payload = json.loads(request.POST.get("payload", "{}"))
            preview_front = request.FILES.get("preview_front")
            preview_back = request.FILES.get("preview_back")
        else:
            payload = json.loads(request.body.decode("utf-8"))
            preview_front = preview_back = None
        variant_id = payload.pop("variant_id", None)
        vendor_listing_id = payload.pop("vendor_listing_id", None)
        variant = get_object_or_404(ProductVariant, id=variant_id, product=product, is_active=True) if variant_id else None
        vendor_listing = get_object_or_404(
            VendorProduct.objects.select_related("vendor"),
            pk=vendor_listing_id,
            product=product,
            status=VendorProduct.Status.ACTIVE,
            vendor__status=Vendor.Status.ACTIVE,
        ) if vendor_listing_id else None
        design = save_design_draft(request=request, product=product, payload=payload, variant=variant)
        update_fields = []
        if preview_front:
            design.temp_preview_front_path = save_design_preview_to_temp(
                draft=design,
                preview_file=preview_front,
                side="front",
            )
            update_fields.append("temp_preview_front_path")
        if preview_back:
            design.temp_preview_back_path = save_design_preview_to_temp(
                draft=design,
                preview_file=preview_back,
                side="back",
            )
            update_fields.append("temp_preview_back_path")
        if update_fields:
            update_fields.append("updated_at")
            design.save(update_fields=update_fields)
        item = add_design_to_cart(request, design=design, quantity=1, vendor_listing=vendor_listing)
    except Exception as exc:
        return JsonResponse({"ok": False, "message": str(exc) or "طراحی قابل افزودن به سبد نیست."}, status=400)
    totals = _cart_totals(item.cart, request)
    return JsonResponse({"ok": True, **totals, "item_id": item.id, "design_id": str(design.uuid), "design_code": design.design_code, "total_price": design.total_price, "message": "طراحی با موفقیت به سبد خرید اضافه شد."})

@require_POST
def cart_add_view(request):
    product_id = request.POST.get("product_id")
    variant_id = request.POST.get("variant_id") or None
    vendor_listing_id = request.POST.get("vendor_listing_id") or None
    quantity = request.POST.get("quantity", "1")
    product = get_object_or_404(Product.objects.select_related("category"), pk=product_id, is_active=True, category__is_active=True)
    vendor_listing = get_object_or_404(
        VendorProduct.objects.select_related("vendor"),
        pk=vendor_listing_id,
        product=product,
        status=VendorProduct.Status.ACTIVE,
        vendor__status=Vendor.Status.ACTIVE,
        vendor__user__is_active=True,
    ) if vendor_listing_id else None
    variant = None
    if variant_id:
        variant = get_object_or_404(ProductVariant, pk=variant_id, product=product, is_active=True)
    try:
        item = add_to_cart(request, product=product, variant=variant, vendor_listing=vendor_listing, quantity=quantity)
    except (ValueError, TypeError):
        message = "اطلاعات انتخاب‌شده برای افزودن به سبد صحیح نیست."
        try:
            requested_quantity = int(quantity)
        except (TypeError, ValueError):
            requested_quantity = 0
        if variant is not None and requested_quantity > variant.stock_quantity:
            message = "تعداد انتخاب‌شده بیشتر از موجودی است."
        if _is_json_request(request):
            return JsonResponse({"ok": False, "message": message}, status=400)
        messages.error(request, message)
        return redirect(product.get_absolute_url())

    totals = _cart_totals(item.cart, request)
    if _is_json_request(request):
        return JsonResponse({"ok": True, **totals, "item_id": item.id, "variant_id": item.variant_id, "vendor_listing_id": item.vendor_listing_id, "quantity": item.quantity, "message": "محصول به سبد خرید اضافه شد."})
    messages.success(request, "محصول به سبد خرید اضافه شد.")
    return redirect("orders:cart")


@require_POST
def cart_update_view(request, item_id):
    try:
        quantity = int(request.POST.get("quantity", "1"))
        item = update_cart_item(request, item_id, quantity)
        message = "سبد خرید بروزرسانی شد."
        status = 200
    except (ValueError, TypeError, CartItem.DoesNotExist):
        message = "تعداد انتخاب‌شده بیشتر از موجودی است یا معتبر نیست."
        status = 400
        item = None

    if _is_json_request(request):
        totals = _cart_totals(get_active_cart(request), request)
        payload = {"ok": status == 200, "message": message, **totals}
        if item is not None:
            payload.update({"item_id": item.id, "quantity": item.quantity, "line_total": item.line_total, "stock": item.variant.stock_quantity if item.variant_id else None})
        return JsonResponse(payload, status=status)
    if status == 200:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect("orders:cart")


@require_POST
def cart_remove_view(request, item_id):
    remove_cart_item(request, item_id)
    if _is_json_request(request):
        return JsonResponse({"ok": True, **_cart_totals(get_active_cart(request), request)})
    messages.success(request, "محصول از سبد خرید حذف شد.")
    return redirect("orders:cart")


@require_POST
def cart_clear_view(request):
    clear_cart(request)
    _remember_cart_count(request, 0)
    if _is_json_request(request):
        return JsonResponse({"ok": True, "count": 0, "subtotal": 0})
    messages.success(request, "سبد خرید خالی شد.")
    return redirect("orders:cart")


@login_required
def checkout_view(request):
    cart = get_active_cart(request)
    addresses = list(
        request.user.addresses
        .select_related("city", "city__province")
        .order_by("-is_default", "-id")
    )
    items = list(
        cart.items
        .select_related("product", "variant__color", "variant__size")
        .order_by("added_at", "id")
    )

    if not items:
        messages.info(request, "سبد خرید شما خالی است.")
        return redirect("orders:cart")

    if request.method == "POST":
        address_id = request.POST.get("address_id")
        note = request.POST.get("customer_note", "")
        try:
            address = Address.objects.select_related("city", "city__province", "user").get(
                pk=address_id,
                user=request.user,
            )
            order = create_order_from_cart(
                user=request.user,
                cart=cart,
                address=address,
                customer_note=note,
            )
        except (Address.DoesNotExist, ValueError) as exc:
            messages.error(request, str(exc) or "لطفاً یک آدرس معتبر انتخاب کنید.")
        else:
            _remember_cart_count(request, 0)
            invalidate_product_cart_cache(request)
            return redirect("orders:payment", order_uuid=order.uuid)

    subtotal = sum(item.line_total for item in items)
    selected_address_id = request.POST.get("address_id") if request.method == "POST" else None
    if not selected_address_id:
        selected_address = next((address for address in addresses if address.is_default), None)
        selected_address_id = selected_address.pk if selected_address else None

    return render(
        request,
        "orders/checkout.html",
        {
            "cart": cart,
            "items": items,
            "addresses": addresses,
            "selected_address_id": selected_address_id,
            "subtotal": subtotal,
            "shipping_amount": 0,
            "total_amount": subtotal,
        },
    )


@login_required
def orders_list_view(request):
    orders = (
        Order.objects
        .filter(user=request.user)
        .annotate(item_count=Count("items"))
        .order_by("-created_at")
    )
    return render(request, "orders/list.html", {"orders": orders})


@login_required
def order_detail_view(request, order_uuid):
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
            "custom_design",
        )
.annotate(primary_image_url=primary_image_url)
        .order_by("id")
    )

    order = get_object_or_404(
        Order.objects.only(
            "id",
            "uuid",
            "number",
            "user_id",
            "status",
            "payment_status",
            "payment_reference",
            "created_at",
            "paid_at",
            "shipping_recipient",
            "shipping_phone",
            "shipping_province",
            "shipping_city",
            "shipping_postal_code",
            "shipping_address",
            "shipping_title",
            "subtotal",
            "discount_amount",
            "shipping_amount",
            "total_amount",
            "customer_note",
        ).prefetch_related(
            Prefetch("items", queryset=item_qs)
        ),
        uuid=order_uuid,
        user=request.user,
    )
    return render(request, "orders/detail.html", {"order": order})


@login_required
def order_payment_view(request, order_uuid):
    order = get_object_or_404(
        Order.objects.only(
            "id",
            "uuid",
            "number",
            "status",
            "payment_status",
            "payment_reference",
            "paid_at",
            "total_amount",
            "user_id",
        ),
        uuid=order_uuid,
        user=request.user,
    )

    if order.payment_status == Order.PaymentStatus.PAID:
        return redirect("orders:detail", order_uuid=order.uuid)

    if request.method == "POST":
        result = request.POST.get("result")
        if result not in {"success", "failed"}:
            messages.error(request, "نتیجه پرداخت نامعتبر است.")
            return redirect("orders:payment", order_uuid=order.uuid)

        try:
            order, changed = process_manual_payment(
                order=order,
                success=result == "success",
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("orders:payment", order_uuid=order.uuid)

        if result == "success":
            messages.success(request, "پرداخت با موفقیت ثبت شد.")
            return redirect("orders:invoice", order_uuid=order.uuid)

        messages.error(request, "پرداخت ناموفق بود. سفارش شما حذف نشده و می‌توانید دوباره تلاش کنید.")
        return redirect("orders:detail", order_uuid=order.uuid)

    return render(request, "orders/payment.html", {"order": order})


@login_required
def invoice_view(request, order_uuid):
    order = get_object_or_404(
        Order.objects.only(
            "id",
            "uuid",
            "number",
            "payment_status",
            "payment_reference",
            "created_at",
            "shipping_recipient",
            "shipping_phone",
            "shipping_title",
            "shipping_province",
            "shipping_city",
            "shipping_address",
            "shipping_postal_code",
            "subtotal",
            "discount_amount",
            "shipping_amount",
            "total_amount",
            "user_id",
        ).prefetch_related(
            Prefetch(
                "items",
                queryset=OrderItem.objects.only(
                    "id",
                    "order_id",
                    "product_name",
                    "color_name",
                    "size_name",
                    "variant_sku",
                    "quantity",
                    "unit_price",
                    "line_total",
                ).order_by("id"),
            )
        ),
        uuid=order_uuid,
        user=request.user,
        payment_status=Order.PaymentStatus.PAID,
    )
    return render(request, "orders/invoice.html", {"order": order})
