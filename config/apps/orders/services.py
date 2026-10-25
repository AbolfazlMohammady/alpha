from __future__ import annotations

from django.db import transaction
from django.db.models import Sum

from .models import Cart, CartItem, Order, OrderItem
from apps.customizer.models import DesignDraft


def _strict_quantity(value):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("تعداد باید عدد صحیح باشد.")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("تعداد باید عدد صحیح باشد.") from exc


CART_SESSION_KEY = "babaei_cart_session"
CART_COUNT_SESSION_KEY = "babaei_cart_item_count"
CART_PRODUCTS_SESSION_KEY = "babaei_cart_products"
AUTH_USER_SESSION_KEY = "_auth_user_id"


def _ensure_session_key(request) -> str:
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def _authenticated_user_id(request):
    return request.session.get(AUTH_USER_SESSION_KEY)


def get_active_cart(request) -> Cart:
    cached_cart = getattr(request, "_babaei_active_cart", None)
    if cached_cart is not None:
        return cached_cart
    user_id = _authenticated_user_id(request)
    if user_id:
        cart, _ = Cart.objects.get_or_create(user_id=user_id, status=Cart.Status.ACTIVE)
    else:
        session_key = _ensure_session_key(request)
        if request.session.get(CART_SESSION_KEY) != session_key:
            request.session[CART_SESSION_KEY] = session_key
        cart, _ = Cart.objects.get_or_create(session_key=session_key, user=None, status=Cart.Status.ACTIVE)
    request._babaei_active_cart = cart
    return cart


def _product_cart_cache(request) -> dict:
    value = getattr(request, "_babaei_cart_products", None)
    if value is None:
        value = request.session.get(CART_PRODUCTS_SESSION_KEY, {})
        if not isinstance(value, dict):
            value = {}
        request._babaei_cart_products = value
    return value


def _save_product_cart_cache(request, cache: dict) -> None:
    request.session[CART_PRODUCTS_SESSION_KEY] = cache
    request._babaei_cart_products = cache


def cache_cart_items(request, items) -> None:
    cache = {}
    for item in items:
        cache.setdefault(str(item.product_id), {})[str(item.variant_id) if item.variant_id else "base"] = item.quantity
    _save_product_cart_cache(request, cache)


def invalidate_product_cart_cache(request) -> None:
    request.session.pop(CART_PRODUCTS_SESSION_KEY, None)
    request._babaei_cart_products = {}


def _cache_item(request, item: CartItem) -> None:
    cache = _product_cart_cache(request)
    cache.setdefault(str(item.product_id), {})[str(item.variant_id) if item.variant_id else "base"] = item.quantity
    _save_product_cart_cache(request, cache)


def get_product_cart_variants(request, product_id: int):
    cached = _product_cart_cache(request)
    product_data = cached.get(str(product_id))
    if product_data is not None:
        return {None if key == "base" else int(key): int(value) for key, value in product_data.items()}

    user_id = _authenticated_user_id(request)
    if user_id:
        rows = CartItem.objects.filter(cart__user_id=user_id, cart__status=Cart.Status.ACTIVE, product_id=product_id).values_list("variant_id", "quantity")
    else:
        session_key = request.session.get(CART_SESSION_KEY) or request.session.session_key
        if not session_key:
            return {}
        rows = CartItem.objects.filter(cart__session_key=session_key, cart__user__isnull=True, cart__status=Cart.Status.ACTIVE, product_id=product_id).values_list("variant_id", "quantity")
    result = dict(rows)
    cached[str(product_id)] = {"base" if variant_id is None else str(variant_id): quantity for variant_id, quantity in result.items()}
    _save_product_cart_cache(request, cached)
    return result


def merge_guest_cart(request, user) -> None:
    session_key = request.session.get(CART_SESSION_KEY) or request.session.session_key
    if not session_key:
        return
    guest = Cart.objects.filter(session_key=session_key, user__isnull=True, status=Cart.Status.ACTIVE).first()
    if not guest:
        return
    with transaction.atomic():
        user_cart, _ = Cart.objects.get_or_create(user=user, status=Cart.Status.ACTIVE)
        for guest_item in guest.items.select_related("product", "variant", "custom_design", "vendor_listing").select_for_update(of=("self",)):
            if guest_item.custom_design_id:
                design = guest_item.custom_design
                design.user = user
                design.session_key = ""
                design.save(update_fields=("user", "session_key", "updated_at"))
                item, created = CartItem.objects.get_or_create(
                    cart=user_cart,
                    custom_design=design,
                    defaults={
                        "product": guest_item.product,
                        "variant": guest_item.variant,
                        "vendor_listing": guest_item.vendor_listing,
                        "quantity": guest_item.quantity,
                    },
                )
            else:
                item, created = CartItem.objects.get_or_create(
                    cart=user_cart,
                    product=guest_item.product,
                    variant=guest_item.variant,
                    vendor_listing=guest_item.vendor_listing,
                    custom_design=None,
                    defaults={"quantity": guest_item.quantity},
                )
            if not created:
                item.quantity += guest_item.quantity
                if item.vendor_listing_id:
                    item.quantity = min(item.quantity, item.vendor_listing.stock_quantity)
                elif item.variant_id:
                    item.quantity = min(item.quantity, item.variant.stock_quantity)
                item.save(update_fields=["quantity", "updated_at"])
        guest.status = Cart.Status.CONVERTED
        guest.save(update_fields=["status", "updated_at"])
    request.session.pop(CART_SESSION_KEY, None)
    invalidate_product_cart_cache(request)
    merged_count = user_cart.item_count
    request.session[CART_COUNT_SESSION_KEY] = merged_count
    request._babaei_cart_item_count = merged_count


def add_design_to_cart(request, *, design: DesignDraft, quantity=1, vendor_listing=None) -> CartItem:
    quantity = _strict_quantity(quantity)
    if quantity < 1:
        raise ValueError("تعداد باید حداقل ۱ باشد.")
    if design.status != DesignDraft.Status.DRAFT:
        raise ValueError("این طراحی دیگر قابل افزودن به سبد نیست.")
    if design.product.marketplace_only and vendor_listing is None:
        raise ValueError("این محصول فقط از طریق فروشنده فعال قابل سفارش است.")
    session_key = _ensure_session_key(request)
    user_id = _authenticated_user_id(request)
    if design.user_id and str(design.user_id) != str(user_id):
        raise ValueError("این طراحی متعلق به کاربر دیگری است.")
    if not design.user_id and design.session_key != session_key:
        raise ValueError("این طراحی متعلق به نشست فعلی نیست.")

    with transaction.atomic():
        if vendor_listing is not None:
            from apps.marketplace.models import VendorProduct, Vendor
            vendor_listing = VendorProduct.objects.select_for_update().select_related("vendor").get(
                pk=vendor_listing.pk,
                product_id=design.product_id,
                status=VendorProduct.Status.ACTIVE,
                vendor__status=Vendor.Status.ACTIVE,
                vendor__user__is_active=True,
                supports_custom_printing=True,
            )
        cart = get_active_cart(request)
        item = CartItem.objects.filter(cart=cart, custom_design=design).select_for_update().first()
        if item and item.vendor_listing_id != getattr(vendor_listing, "id", None):
            raise ValueError("این طراحی قبلاً با فروشنده دیگری به سبد اضافه شده است.")
        if vendor_listing is not None:
            if item and (
                item.vendor_sale_unit_snapshot != vendor_listing.sale_unit
                or item.vendor_units_per_order_snapshot != vendor_listing.units_per_order
            ):
                raise ValueError("واحد فروش این محصول تغییر کرده است؛ طراحی را از سبد حذف و دوباره اضافه کن.")
            cart_listing_quantity = CartItem.objects.filter(
                cart=cart, vendor_listing=vendor_listing
            ).aggregate(total=Sum("quantity"))["total"] or 0
            if cart_listing_quantity + quantity > vendor_listing.stock_quantity:
                raise ValueError("موجودی فروشنده برای مجموع تعداد این طراحی در سبد کافی نیست.")
        if item:
            item.quantity += quantity
            item.save(update_fields=("quantity", "updated_at"))
        else:
            item = CartItem.objects.create(
                cart=cart,
                product=design.product,
                variant=design.variant,
                custom_design=design,
                vendor_listing=vendor_listing,
                quantity=quantity,
                vendor_sale_unit_snapshot=vendor_listing.sale_unit if vendor_listing is not None else "عدد",
                vendor_units_per_order_snapshot=vendor_listing.units_per_order if vendor_listing is not None else 1,
            )
    return item

def add_to_cart(request, *, product, variant=None, custom_design=None, vendor_listing=None, quantity=1) -> CartItem:
    quantity = _strict_quantity(quantity)
    if quantity < 1:
        raise ValueError("تعداد باید حداقل ۱ باشد.")
    if custom_design is not None and (custom_design.product_id != product.id or custom_design.status not in {"draft", "cart"}):
        raise ValueError("طراحی انتخاب‌شده معتبر نیست.")
    if getattr(product, "marketplace_only", False) and vendor_listing is None:
        raise ValueError("این محصول فقط از طریق فروشنده فعال قابل سفارش است.")
    if vendor_listing is not None:
        from apps.marketplace.models import VendorProduct, Vendor
        vendor_listing = VendorProduct.objects.select_related("vendor").get(
            pk=vendor_listing.pk,
            product_id=product.id,
            status=VendorProduct.Status.ACTIVE,
            vendor__status=Vendor.Status.ACTIVE,
            vendor__user__is_active=True,
        )
        if vendor_listing.stock_quantity < quantity:
            raise ValueError("موجودی این فروشنده برای تعداد انتخاب‌شده کافی نیست.")
        if custom_design is not None and not vendor_listing.supports_custom_printing:
            raise ValueError("این فروشنده چاپ سفارشی این محصول را پشتیبانی نمی‌کند.")
    with transaction.atomic():
        cart = get_active_cart(request)
        if vendor_listing is not None:
            from apps.marketplace.models import VendorProduct, Vendor
            vendor_listing = VendorProduct.objects.select_for_update().select_related("vendor").get(
                pk=vendor_listing.pk,
                product_id=product.id,
                status=VendorProduct.Status.ACTIVE,
                vendor__status=Vendor.Status.ACTIVE,
                vendor__user__is_active=True,
            )
            cart_listing_quantity = CartItem.objects.filter(cart=cart, vendor_listing=vendor_listing).aggregate(total=Sum("quantity"))["total"] or 0
            if cart_listing_quantity + quantity > vendor_listing.stock_quantity:
                raise ValueError("موجودی فروشنده برای مجموع تعداد این محصول در سبد کافی نیست.")
        if variant is not None:
            if variant.product_id != product.id:
                raise ValueError("ترکیب انتخاب‌شده متعلق به این محصول نیست.")
            variant = type(variant).objects.select_for_update().get(pk=variant.pk)
            if not variant.is_active or not product.is_active or not product.category.is_active:
                raise ValueError("این محصول دیگر قابل خرید نیست.")
            if vendor_listing is None and variant.stock_quantity < quantity:
                raise ValueError("تعداد انتخاب‌شده بیشتر از موجودی است.")
        elif product.variants.filter(is_active=True).exists():
            raise ValueError("لطفاً رنگ و سایز محصول را انتخاب کنید.")
        lookup = {"cart": cart, "custom_design": custom_design} if custom_design is not None else {
            "cart": cart, "product": product, "variant": variant, "custom_design": None,
            "vendor_listing": vendor_listing,
        }
        item, created = CartItem.objects.select_for_update().get_or_create(
            **lookup,
            defaults={
                "quantity": quantity,
                "vendor_sale_unit_snapshot": vendor_listing.sale_unit if vendor_listing is not None else "عدد",
                "vendor_units_per_order_snapshot": vendor_listing.units_per_order if vendor_listing is not None else 1,
            },
        )
        expected_listing_id = vendor_listing.pk if vendor_listing is not None else None
        if custom_design is not None and item.vendor_listing_id != expected_listing_id:
            raise ValueError("این طراحی قبلاً با فروشنده دیگری به سبد اضافه شده است.")
        if vendor_listing is not None and (
            item.vendor_sale_unit_snapshot != vendor_listing.sale_unit
            or item.vendor_units_per_order_snapshot != vendor_listing.units_per_order
        ):
            raise ValueError("واحد فروش این محصول تغییر کرده است؛ آن را از سبد حذف و دوباره اضافه کن.")
        if not created:
            new_quantity = item.quantity + quantity
            available = vendor_listing.stock_quantity if vendor_listing is not None else (variant.stock_quantity if variant is not None else None)
            if vendor_listing is None and available is not None and new_quantity > available:
                raise ValueError("تعداد انتخاب‌شده بیشتر از موجودی است.")
            item.quantity = new_quantity
            item.save(update_fields=["quantity", "updated_at"])
    _cache_item(request, item)
    return item


def update_cart_item(request, item_id: int, quantity: int) -> CartItem:
    quantity = _strict_quantity(quantity)
    if quantity < 1:
        raise ValueError("تعداد باید حداقل ۱ باشد.")
    with transaction.atomic():
        cart = get_active_cart(request)
        item = CartItem.objects.select_for_update().select_related("variant", "vendor_listing").get(cart=cart, pk=item_id)
        if item.vendor_listing_id:
            from apps.marketplace.models import VendorProduct
            listing = VendorProduct.objects.select_for_update().get(pk=item.vendor_listing_id)
            if (
                listing.status != VendorProduct.Status.ACTIVE
                or item.vendor_sale_unit_snapshot != listing.sale_unit
                or item.vendor_units_per_order_snapshot != listing.units_per_order
            ):
                raise ValueError("وضعیت یا واحد فروش این محصول تغییر کرده است؛ آن را حذف و دوباره از صفحه محصول اضافه کن.")
            cart_listing_quantity = CartItem.objects.filter(cart=cart, vendor_listing=listing).aggregate(total=Sum("quantity"))["total"] or 0
            requested_total = cart_listing_quantity - item.quantity + quantity
            if requested_total > listing.stock_quantity:
                raise ValueError("مجموع تعداد انتخاب‌شده بیشتر از موجودی فروشنده است.")
        elif item.variant_id:
            variant = type(item.variant).objects.select_for_update().get(pk=item.variant_id)
            if quantity > variant.stock_quantity:
                raise ValueError("تعداد انتخاب‌شده بیشتر از موجودی است.")
        item.quantity = quantity
        item.save(update_fields=["quantity", "updated_at"])
    _cache_item(request, item)
    return item


def remove_cart_item(request, item_id: int) -> None:
    cart = get_active_cart(request)
    item = (
        CartItem.objects
        .filter(cart=cart, pk=item_id)
        .values("product_id", "variant_id", "custom_design_id")
        .first()
    )
    if not item:
        return

    CartItem.objects.filter(cart=cart, pk=item_id).delete()

    # A design that has not reached an order is disposable. Do not keep it as
    # an admin-visible record after the customer removes it from the cart.
    if item["custom_design_id"]:
        DesignDraft.objects.filter(
            pk=item["custom_design_id"],
            status__in=[DesignDraft.Status.DRAFT, DesignDraft.Status.CART],
        ).delete()

    cache = _product_cart_cache(request)
    product_cache = cache.get(str(item["product_id"]))
    if product_cache:
        product_cache.pop(str(item["variant_id"]) if item["variant_id"] else "base", None)
        if not product_cache:
            cache.pop(str(item["product_id"]), None)
    _save_product_cart_cache(request, cache)


def clear_cart(request) -> None:
    cart = get_active_cart(request)
    design_ids = list(
        cart.items
        .exclude(custom_design_id=None)
        .values_list("custom_design_id", flat=True)
    )
    cart.items.all().delete()

    if design_ids:
        DesignDraft.objects.filter(
            id__in=design_ids,
            status__in=[DesignDraft.Status.DRAFT, DesignDraft.Status.CART],
        ).delete()

    invalidate_product_cart_cache(request)


def create_order_from_cart(*, user, cart, address, customer_note="", shipping_quote_ids=None):
    """Convert the active cart into an immutable order snapshot."""
    from apps.shop.models import ProductVariant

    with transaction.atomic():
        locked_cart = Cart.objects.select_for_update().get(
            pk=cart.pk,
            user=user,
            status=Cart.Status.ACTIVE,
        )
        items = list(
            locked_cart.items
            .select_related(
                "product",
                "product__category",
                "variant__color",
                "variant__size",
                "custom_design",
            )
            .select_for_update(of=("self",))
            .order_by("added_at", "id")
        )
        if not items:
            raise ValueError("سبد خرید خالی است.")

        order_rows = []
        subtotal = 0
        listing_quantities = {}
        listing_stock_quantities = {}
        for cart_item in items:
            if cart_item.vendor_listing_id:
                listing_stock_quantities[cart_item.vendor_listing_id] = listing_stock_quantities.get(cart_item.vendor_listing_id, 0) + cart_item.quantity
                if cart_item.custom_design_id is None:
                    listing_quantities[cart_item.vendor_listing_id] = listing_quantities.get(cart_item.vendor_listing_id, 0) + cart_item.quantity

        for item in items:
            product = item.product
            design = item.custom_design
            if not product.is_active or not product.category.is_active:
                raise ValueError("این لباس دیگر قابل سفارش نیست.")
            if product.marketplace_only and not item.vendor_listing_id:
                raise ValidationError("این محصول فقط از طریق فروشنده فعال قابل سفارش است.")
            if design is not None and (design.status not in {DesignDraft.Status.DRAFT, DesignDraft.Status.CART} or design.product_id != product.id):
                raise ValueError("طراحی این آیتم دیگر قابل سفارش نیست.")

            if design is not None:
                listing = None
                if item.vendor_listing_id:
                    from apps.marketplace.models import VendorProduct
                    listing = VendorProduct.objects.select_for_update().select_related("vendor").get(pk=item.vendor_listing_id)
                    if item.vendor_sale_unit_snapshot != listing.sale_unit or item.vendor_units_per_order_snapshot != listing.units_per_order:
                        raise ValidationError("واحد فروش این محصول از زمان افزودن به سبد تغییر کرده است؛ آن را حذف و دوباره اضافه کن.")
                    if listing.status != VendorProduct.Status.ACTIVE or not listing.vendor.can_receive_orders or not listing.supports_custom_printing:
                        raise ValueError("فروشنده انتخاب‌شده امکان اجرای طراحی سفارشی را ندارد.")
                    if listing.stock_quantity < listing_stock_quantities.get(listing.pk, 0):
                        raise ValueError("ظرفیت/موجودی فروشنده برای مجموع تعداد سفارش کافی نیست.")
                if design.user_id and design.user_id != user.id:
                    raise ValueError("طراحی سفارشی متعلق به این کاربر نیست.")
                unit_price = design.total_price
                line_total = unit_price * item.quantity
                snapshot = dict(design.payload or {})
                snapshot.update({
                    "design_code": design.design_code,
                    "base_price": design.base_price,
                    "total_price": design.total_price,
                    "shirt_color": design.shirt_color,
                    "variant_id": design.variant_id,
                    "sale_unit": item.vendor_listing.sale_unit if item.vendor_listing_id else "عدد",
                    "units_per_order": item.vendor_listing.units_per_order if item.vendor_listing_id else 1,
                })
                if listing is not None and not listing.supports_custom_printing:
                    raise ValueError("فروشنده انتخاب‌شده چاپ سفارشی را پشتیبانی نمی‌کند.")
                order_rows.append({
                    "cart_item": item,
                    "vendor_listing": item.vendor_listing,
                    "variant": design.variant,
                    "unit_price": unit_price,
                    "compare_at_price": None,
                    "variant_sku": getattr(design.variant, "sku", "") if design.variant_id else "",
                    "color_name": getattr(getattr(design.variant, "color", None), "name", "") if design.variant_id else "",
                    "size_name": getattr(getattr(design.variant, "size", None), "name", "") if design.variant_id else "",
                    "line_total": line_total,
                    "custom_design": design,
                    "custom_design_snapshot": snapshot,
                })
                subtotal += line_total
                continue

            listing = None
            if item.vendor_listing_id:
                from apps.marketplace.models import VendorProduct
                listing = VendorProduct.objects.select_for_update().select_related("vendor").get(pk=item.vendor_listing_id)
                if item.vendor_sale_unit_snapshot != listing.sale_unit or item.vendor_units_per_order_snapshot != listing.units_per_order:
                    raise ValidationError("واحد فروش این محصول از زمان افزودن به سبد تغییر کرده است؛ آن را حذف و دوباره اضافه کن.")
                if listing.status != VendorProduct.Status.ACTIVE or not listing.vendor.can_receive_orders:
                    raise ValueError(f"فروشنده محصول «{product.name}» در حال حاضر سفارش نمی‌پذیرد.")
                if listing.stock_quantity < listing_stock_quantities.get(listing.pk, 0):
                    raise ValueError(f"موجودی فروشنده برای مجموع تعداد محصول «{product.name}» کافی نیست.")
            variant = None
            if item.variant_id:
                variant = (
                    ProductVariant.objects
                    .select_for_update()
                    .select_related("color", "size")
                    .get(pk=item.variant_id, product_id=product.id)
                )
                if not variant.is_active:
                    raise ValueError(f"ترکیب «{product.name}» دیگر قابل سفارش نیست.")
                if listing is None and variant.stock_quantity < item.quantity:
                    raise ValueError(f"موجودی «{product.name}» برای تعداد انتخاب‌شده کافی نیست.")
                unit_price = listing.retail_price if listing else variant.effective_price
                compare_at_price = listing.compare_at_price if listing else variant.effective_compare_at_price
                variant_sku = variant.sku
                color_name = variant.color.name
                size_name = variant.size.name
            else:
                unit_price = listing.retail_price if listing else product.base_price
                compare_at_price = listing.compare_at_price if listing else product.compare_at_price
                variant_sku = ""
                color_name = ""
                size_name = ""
            if listing is not None and listing.wholesale_enabled:
                tier = listing.wholesale_tiers.filter(minimum_quantity__lte=listing_quantities.get(listing.pk, 0)).order_by("-minimum_quantity").first()
                if tier:
                    unit_price = tier.unit_price

            line_total = unit_price * item.quantity
            subtotal += line_total
            order_rows.append({
                "cart_item": item,
                "vendor_listing": listing,
                "variant": variant,
                "unit_price": unit_price,
                "compare_at_price": compare_at_price,
                "variant_sku": variant_sku,
                "color_name": color_name,
                "size_name": size_name,
                "line_total": line_total,
                "custom_design": None,
                "custom_design_snapshot": {},
            })

        has_vendor_items = any(row.get("vendor_listing") is not None for row in order_rows)
        has_platform_items = any(row.get("vendor_listing") is None for row in order_rows)
        if has_vendor_items and has_platform_items:
            raise ValidationError("سبد خرید شامل کالاهای فروشندگان و کالاهای خارج از مارکت‌پلیس است؛ لطفاً آن‌ها را در سفارش‌های جداگانه ثبت کنید.")

        from apps.marketplace.services import consume_shipping_quotes
        shipping_amount, used_shipping_quotes = consume_shipping_quotes(
            user=user,
            cart=locked_cart,
            address=address,
            items=items,
            quote_ids=shipping_quote_ids or [],
        )
        if subtotal + shipping_amount <= 0:
            raise ValidationError("مبلغ نهایی سفارش باید مثبت باشد؛ سفارش رایگان باید از گردش جداگانه ثبت شود.")

        recipient_name = " ".join(str(address.recipient_display_name or "").split())
        if len(recipient_name) < 2:
            raise ValueError("برای ثبت سفارش، نام و نام خانوادگی گیرنده را در پروفایل یا خود آدرس تکمیل کنید.")

        order = Order.objects.create(
            user=user,
            status=Order.Status.PENDING,
            payment_status=Order.PaymentStatus.UNPAID,
            shipping_status=Order.ShippingStatus.PENDING,
            shipping_title=address.title,
            shipping_recipient=recipient_name,
            shipping_phone=str(address.phone),
            shipping_province=address.city.province.name,
            shipping_city=address.city.name,
            shipping_postal_code=address.postal_code,
            shipping_address=address.description or address.title,
            subtotal=subtotal,
            discount_amount=0,
            shipping_amount=shipping_amount,
            total_amount=subtotal + shipping_amount,
            currency="IRT",
            customer_note=customer_note.strip(),
        )
        if used_shipping_quotes:
            from apps.marketplace.models import ShippingQuote
            ShippingQuote.objects.filter(pk__in=[quote.pk for quote in used_shipping_quotes]).update(order=order)

        OrderItem.objects.bulk_create([
            OrderItem(
                order=order,
                product=row["cart_item"].product,
                vendor_listing=row.get("vendor_listing"),
                variant=row["variant"],
                product_name=(row["custom_design"].design_code if row.get("custom_design") else row["cart_item"].product.name),
                variant_sku=row["variant_sku"],
                color_name=row["color_name"],
                size_name=row["size_name"],
                unit_price=row["unit_price"],
                compare_at_price=row["compare_at_price"],
                quantity=row["cart_item"].quantity,
                line_total=row["line_total"],
                custom_design=row.get("custom_design"),
                custom_design_code=row["custom_design"].design_code if row.get("custom_design") else "",
                custom_design_snapshot=row.get("custom_design_snapshot", {}),
                vendor_sale_unit_snapshot=row["vendor_listing"].sale_unit if row.get("vendor_listing") else "عدد",
                vendor_units_per_order_snapshot=row["vendor_listing"].units_per_order if row.get("vendor_listing") else 1,
            )
            for row in order_rows
        ])

        locked_cart.status = Cart.Status.CONVERTED
        locked_cart.save(update_fields=["status", "updated_at"])

    return order


def process_manual_payment(*, order, success):
    """Development-only payment simulator.

    Successful payment locks each variant, verifies stock, decrements inventory,
    and marks the order paid. Failed payment keeps the order pending so it can
    be retried.
    """
    from apps.shop.models import ProductVariant
    from django.utils import timezone

    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)

        if locked_order.payment_status == Order.PaymentStatus.PAID:
            from apps.customizer.services import promote_design_assets_for_order
            promote_design_assets_for_order(locked_order)
            from apps.marketplace.services import create_vendor_orders_for_paid_order
            create_vendor_orders_for_paid_order(locked_order)
            return locked_order, False

        if locked_order.status in {Order.Status.CANCELLED, Order.Status.REFUNDED}:
            raise ValueError("این سفارش دیگر قابل پرداخت نیست.")

        if not success:
            locked_order.payment_status = Order.PaymentStatus.FAILED
            locked_order.payment_reference = f"MANUAL-FAILED-{locked_order.number}"
            locked_order.save(update_fields=["payment_status", "payment_reference", "updated_at"])
            return locked_order, True

        order_items = list(locked_order.items.select_related("product", "variant", "vendor_listing__vendor").select_for_update(of=("self",)))
        for item in order_items:
            if item.vendor_listing_id:
                from apps.marketplace.models import VendorProduct
                listing = VendorProduct.objects.select_for_update().select_related("vendor").get(pk=item.vendor_listing_id)
                if (
                    listing.status != VendorProduct.Status.ACTIVE
                    or not listing.vendor.can_receive_orders
                    or listing.stock_quantity < item.quantity
                ):
                    raise ValueError(f"موجودی یا وضعیت فروشنده برای «{item.product_name}» معتبر نیست.")
                if (
                    item.vendor_sale_unit_snapshot != listing.sale_unit
                    or item.vendor_units_per_order_snapshot != listing.units_per_order
                ):
                    raise ValueError(
                        f"واحد فروش محصول «{item.product_name}» پس از ثبت سفارش تغییر کرده است؛ "
                        "پرداخت متوقف شد تا سفارش با بسته‌بندی جدید اصلاح شود."
                    )
                if item.custom_design_id and not listing.supports_custom_printing:
                    raise ValueError("فروشنده انتخاب‌شده دیگر چاپ سفارشی این محصول را پشتیبانی نمی‌کند.")
                listing.stock_quantity -= item.quantity
                listing.save(update_fields=["stock_quantity", "updated_at"])
                continue
            if not item.variant_id:
                continue
            variant = ProductVariant.objects.select_for_update().get(pk=item.variant_id)
            if not variant.is_active or variant.stock_quantity < item.quantity:
                raise ValueError(f"موجودی «{item.product_name}» دیگر کافی نیست.")
            variant.stock_quantity -= item.quantity
            variant.save(update_fields=["stock_quantity"])

        from apps.customizer.services import promote_design_assets_for_order
        promote_design_assets_for_order(locked_order)

        locked_order.payment_status = Order.PaymentStatus.PAID
        locked_order.status = Order.Status.PAID
        locked_order.payment_reference = f"MANUAL-{locked_order.number}"
        locked_order.paid_at = timezone.now()

        locked_order.save(
            update_fields=[
                "payment_status",
                "status",
                "payment_reference",
                "paid_at",
                "updated_at",
            ]
        )
        # Split seller orders and post the financial journal only when every
        # order line has an explicit vendor listing. Legacy catalog orders keep
        # their existing workflow until sellers are assigned.
        from apps.marketplace.services import create_vendor_orders_for_paid_order
        create_vendor_orders_for_paid_order(locked_order)
        return locked_order, True
