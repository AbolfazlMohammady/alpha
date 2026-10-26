from __future__ import annotations

import json
from datetime import timedelta

from PIL import Image, UnidentifiedImageError

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .carriers import CarrierError, CarrierNotConfigured, get_carrier, validate_quote_input
from apps.orders.models import Cart, CartItem, Order
from apps.users.models import Address, RoleUser
from apps.shop.models import Category, Product
from .models import CategoryRequest, FinancialReconciliation, SettlementBatch, Shipment, Vendor, VendorOrder, VendorProduct, VendorProductSubmission, WholesalePriceTier
from .services import _strict_int, approve_settlement, create_shipping_quote, mark_vendor_order_delivered, reconcile_shipment_actual_cost, record_carrier_invoice_payment, record_external_reconciliation, record_full_order_refund, record_gateway_settlement, record_payout_result, trial_balance
from .payouts import PayoutError, PayoutNotConfigured, submit_settlement_payout


def _validate_product_upload(uploaded_file):
    if uploaded_file is None:
        raise ValidationError("تصویر اصلی محصول الزامی است.")
    if uploaded_file.size > 5 * 1024 * 1024:
        raise ValidationError("حجم تصویر باید حداکثر ۵ مگابایت باشد.")
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            image_format = (image.format or "").upper()
            if image_format not in {"JPEG", "PNG", "WEBP"}:
                raise ValidationError("فرمت تصویر باید JPG، PNG یا WebP باشد.")
            if image.width < 1 or image.height < 1 or image.width * image.height > 30_000_000:
                raise ValidationError("ابعاد تصویر معتبر نیست یا بیش از حد بزرگ است.")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("فایل ارسالی یک تصویر سالم و معتبر نیست.") from exc
    finally:
        uploaded_file.seek(0)
    # Do not trust the user's filename extension; keep storage/content-type
    # handling aligned with the actual, verified image format.
    extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[image_format]
    uploaded_file.name = f"product-upload.{extension}"
    return uploaded_file


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
    # Refresh the role from the database rather than relying on a stale in-memory
    # user instance. Some custom account-editing flows may persist the display
    # label instead of the TextChoices value, so accept both canonical forms.
    user.refresh_from_db(fields=["role"])
    role_value = str(getattr(user, "role", "") or "").strip().lower()
    is_store_manager = role_value in {
        str(RoleUser.STORE_MANAGER).lower(),
        "مدیر فروشگاه",
    }
    try:
        return Vendor.objects.get(user=user)
    except Vendor.DoesNotExist as exc:
        # A store-manager role alone did not create the marketplace Vendor row.
        # Create a pending profile so the seller can complete their store setup;
        # order acceptance still depends on Vendor.Status.ACTIVE.
        if not is_store_manager:
            raise PermissionDenied(
                f"برای این حساب پروفایل فروشگاه وجود ندارد و نقش ذخیره‌شده "
                f"({role_value or 'خالی'}) مدیر فروشگاه نیست."
            ) from exc
        display_name = user.get_full_name().strip() or f"فروشگاه {user.pk}"
        vendor, _ = Vendor.objects.get_or_create(
            user=user,
            defaults={
                "store_name": display_name[:160],
                "slug": f"store-{user.pk}-{user.uuid.hex[:8]}",
                "status": Vendor.Status.PENDING,
            },
        )
        return vendor


PORTAL_SECTIONS = {
    "new-product": {
        "title": "ثبت محصول جدید",
        "description": "ثبت محصولی که هنوز در کاتالوگ مرکزی سایت وجود ندارد و ارسال آن برای بررسی مدیر.",
        "audience": "vendor",
        "next_step": "فرم ثبت محصول در پنل فروشنده قرار دارد.",
    },
    "my-products": {
        "title": "محصولات فروشگاه من",
        "description": "مشاهده آگهی‌های فروش، وضعیت تأیید، قیمت، موجودی و تنظیمات فروش عمده.",
        "audience": "vendor",
        "next_step": "مدیریت محصولات در پنل فروشنده قرار دارد.",
    },
    "vendor-orders": {
        "title": "سفارش‌ها و ارسال",
        "description": "بررسی سفارش‌های فروشگاه، آماده‌سازی، ثبت اطلاعات مرسوله و پیگیری ارسال.",
        "audience": "vendor",
        "next_step": "مدیریت سفارش‌ها در پنل فروشنده قرار دارد.",
    },
    "vendor-settlements": {
        "title": "تسویه‌حساب فروشگاه",
        "description": "مشاهده وضعیت تسویه‌ها و آماده‌سازی اطلاعات مالی فروشگاه.",
        "audience": "vendor",
        "next_step": "اطلاعات حساب و تاریخچه تسویه در پنل فروشنده قرار دارد.",
    },
    "shipping-profile": {
        "title": "اطلاعات مبدأ ارسال",
        "description": "ثبت نشانی، کد پستی، شهر و اطلاعات تماس محل آماده‌سازی بسته‌ها.",
        "audience": "vendor",
        "next_step": "فرم اطلاعات مبدأ ارسال در پنل فروشنده قرار دارد.",
    },
    "financial-profile": {
        "title": "اطلاعات حساب بانکی",
        "description": "ثبت نام صاحب حساب و شبای بانکی برای بررسی و تسویه سهم فروشگاه.",
        "audience": "vendor",
        "next_step": "فرم اطلاعات حساب تسویه در پنل فروشنده قرار دارد.",
    },
    "accounting-overview": {
        "title": "حسابداری مرکزی",
        "description": "صفحه موقت دسترسی به بخش حسابداری فروشگاه‌ها، اسناد مالی و گزارش‌های تسویه.",
        "audience": "admin",
        "next_step": "رابط کاربری حسابداری مرکزی هنوز در حال آماده‌سازی است.",
    },
    "trial-balance": {
        "title": "تراز آزمایشی",
        "description": "نمای موقت گزارش تراز حساب‌ها و کنترل برابری بدهکار و بستانکار.",
        "audience": "admin",
        "next_step": "رابط گزارش تراز آزمایشی هنوز در حال آماده‌سازی است.",
    },
    "reconciliation": {
        "title": "مغایرت‌گیری مالی",
        "description": "صفحه موقت برای بررسی و تطبیق گزارش‌های مالی با منابع بیرونی.",
        "audience": "admin",
        "next_step": "رابط مغایرت‌گیری هنوز در حال آماده‌سازی است.",
    },
    "gateway-settlement": {
        "title": "تسویه درگاه پرداخت",
        "description": "صفحه موقت برای ثبت و بررسی مبالغ تسویه‌شده توسط درگاه پرداخت.",
        "audience": "admin",
        "next_step": "رابط تسویه درگاه هنوز در حال آماده‌سازی است.",
    },
    "carrier-payment": {
        "title": "پرداخت شرکت حمل",
        "description": "صفحه موقت برای بررسی صورتحساب و پرداخت هزینه‌های شرکت حمل‌ونقل.",
        "audience": "admin",
        "next_step": "رابط پرداخت شرکت حمل هنوز در حال آماده‌سازی است.",
    },
    "settlement-queue": {
        "title": "مدیریت تسویه فروشندگان",
        "description": "صفحه موقت برای بررسی، تأیید و پیگیری پرداخت سهم فروشگاه‌های همکار.",
        "audience": "admin",
        "next_step": "رابط مدیریت تسویه فروشندگان هنوز در حال آماده‌سازی است.",
    },
}


@login_required
def portal_section_page(request, section):
    details = PORTAL_SECTIONS.get(section)
    if details is None:
        return JsonResponse({"ok": False, "error": "بخش پیدا نشد."}, status=404)
    if details["audience"] == "admin":
        if not request.user.is_staff:
            return HttpResponseForbidden("این بخش فقط برای مدیران سامانه قابل مشاهده است.")
    else:
        try:
            _vendor_for_user(request.user)
        except PermissionDenied as exc:
            return HttpResponseForbidden(str(exc))
    return render(
        request,
        "marketplace/portal_section.html",
        {"section": details, "section_slug": section},
    )


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
    except PermissionDenied as exc:
        return HttpResponseForbidden(str(exc))
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
@require_http_methods(["GET", "POST"])
def vendor_financial_profile_api(request):
    try:
        vendor = _vendor_for_user(request.user)
        if request.method == "GET":
            iban = vendor.bank_iban or ""
            masked_iban = f"{iban[:4]}{'*' * max(len(iban) - 8, 0)}{iban[-4:]}" if iban else ""
            return JsonResponse({
                "ok": True,
                "bank_account_name": vendor.bank_account_name,
                "bank_iban_masked": masked_iban,
                "bank_details_verified": bool(vendor.bank_details_verified_at),
            })
        payload = _json_body(request)
        allowed = {"bank_account_name", "bank_iban"}
        if set(payload) != allowed:
            return _error("نام صاحب حساب و شماره شبا را با هم ارسال کن.")
        vendor.bank_account_name = str(payload.get("bank_account_name") or "").strip()
        vendor.bank_iban = str(payload.get("bank_iban") or "").strip()
        vendor.full_clean()
        vendor.save(update_fields=("bank_account_name", "bank_iban", "bank_details_verified_at", "updated_at"))
        iban = vendor.bank_iban or ""
        masked_iban = f"{iban[:4]}{'*' * max(len(iban) - 8, 0)}{iban[-4:]}" if iban else ""
        return JsonResponse({
            "ok": True,
            "bank_account_name": vendor.bank_account_name,
            "bank_iban_masked": masked_iban,
            "bank_details_verified": bool(vendor.bank_details_verified_at),
            "message": "اطلاعات بانکی ذخیره شد؛ امکان تسویه پس از بررسی مدیر فعال می‌شود.",
        })
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ValidationError as exc:
        return _error(exc)
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
        "shipping_adjustment": batch.shipping_adjustment,
        "refund_adjustment": batch.refund_adjustment,
        "other_adjustment": batch.other_adjustment,
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
            "carrier_name": str((shipment.provider_payload or {}).get("carrier_name") or shipment.get_provider_display()),
            "payer": shipment.payer,
            "status": shipment.status,
            "tracking_number": shipment.tracking_number,
            "customer_charge": shipment.customer_charge,
            "quoted_cost": shipment.quoted_cost,
            "actual_cost": shipment.actual_cost,
            "label_url": shipment.label_url,
        } for shipment in item.shipments.all()],
    } for item in orders]})


@login_required
@require_http_methods(["GET", "POST"])
def vendor_product_submissions_api(request):
    try:
        vendor = _vendor_for_user(request.user)
        if request.method == "GET":
            categories = Category.objects.filter(is_active=True).order_by("name")
            submissions = vendor.product_submissions.select_related("category", "product").order_by("-created_at")[:20]
            return JsonResponse({
                "ok": True,
                "categories": [{"id": item.id, "name": item.name} for item in categories],
                "results": [{
                    "id": item.id,
                    "name": item.name,
                    "category": item.category.name,
                    "status": item.status,
                    "status_label": item.get_status_display(),
                    "reviewer_note": item.reviewer_note,
                    "product_id": item.product_id,
                    "created_at": item.created_at.isoformat(),
                } for item in submissions],
            })
        if not vendor.can_receive_orders:
            return _error("تا زمان فعال‌شدن فروشگاه، امکان ثبت محصول جدید وجود ندارد.", 403)
        if not request.content_type.startswith("multipart/form-data"):
            return _error("اطلاعات محصول باید همراه تصویر و به‌صورت فرم ارسال شود.")
        allowed = {
            "category_id", "name", "short_description", "description", "retail_price",
            "compare_at_price", "sale_unit", "units_per_order", "stock_quantity", "weight_grams", "package_length_cm",
            "package_width_cm", "package_height_cm", "handling_days", "supports_custom_printing",
            "csrfmiddlewaretoken",
        }
        if set(request.POST.keys()) - allowed or set(request.FILES.keys()) - {"image"}:
            return _error("فیلد ارسالی غیرمجاز است.")
        image = _validate_product_upload(request.FILES.get("image"))
        category_id = int(request.POST.get("category_id", 0))
        category = Category.objects.filter(pk=category_id, is_active=True).first()
        if category is None:
            return _error("دسته‌بندی انتخاب‌شده وجود ندارد یا غیرفعال شده است.", 400)
        compare_value = request.POST.get("compare_at_price", "").strip()
        custom_print = request.POST.get("supports_custom_printing", "false").strip().lower()
        if custom_print not in {"true", "false"}:
            return _error("وضعیت چاپ سفارشی معتبر نیست.")
        submission = VendorProductSubmission(
            vendor=vendor,
            category=category,
            name=request.POST.get("name", "").strip(),
            short_description=strip_tags(request.POST.get("short_description", "")).strip(),
            description=strip_tags(request.POST.get("description", "")).strip(),
            image=image,
            retail_price=int(request.POST.get("retail_price", 0)),
            compare_at_price=int(compare_value) if compare_value else None,
            sale_unit=request.POST.get("sale_unit", "عدد").strip(),
            units_per_order=int(request.POST.get("units_per_order", 1)),
            stock_quantity=int(request.POST.get("stock_quantity", 0)),
            weight_grams=int(request.POST.get("weight_grams", 0)),
            package_length_cm=int(request.POST.get("package_length_cm", 0)),
            package_width_cm=int(request.POST.get("package_width_cm", 0)),
            package_height_cm=int(request.POST.get("package_height_cm", 0)),
            handling_days=int(request.POST.get("handling_days", 2)),
            supports_custom_printing=(custom_print == "true"),
        )
        submission.full_clean()
        submission.save()
        return JsonResponse({
            "ok": True,
            "submission_id": submission.id,
            "status": submission.status,
            "message": "محصول برای بررسی مدیر ارسال شد؛ پس از تأیید، کالا و آگهی فروش فعال می‌شوند.",
        }, status=201)
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ValidationError as exc:
        return _error(exc)
    except (TypeError, ValueError) as exc:
        return _error(exc)


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
            "status_label": listing.get_status_display(),
            "retail_price": listing.retail_price,
            "compare_at_price": listing.compare_at_price,
            "sale_unit": listing.sale_unit,
            "units_per_order": listing.units_per_order,
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
        allowed = {
            "product_id", "retail_price", "compare_at_price", "sale_unit", "units_per_order",
            "stock_quantity", "wholesale_enabled", "supports_custom_printing", "weight_grams",
            "package_length_cm", "package_width_cm", "package_height_cm", "handling_days",
        }
        unknown = set(payload) - allowed
        if unknown:
            return _error("فیلدهای غیرمجاز: " + ", ".join(sorted(unknown)))
        product_id = _strict_int(payload.get("product_id", 0), "شناسه محصول")
        product = get_object_or_404(Product, pk=product_id, is_active=True, category__is_active=True)
        if vendor.listings.filter(product=product).exists():
            return _error("این محصول قبلاً توسط فروشگاه شما ثبت شده است.", 409)
        for flag in ("wholesale_enabled", "supports_custom_printing"):
            if flag in payload and not isinstance(payload[flag], bool):
                return _error(f"{flag} باید true یا false باشد.")
        if payload.get("wholesale_enabled") is True:
            return _error("ابتدا محصول را بدون فروش عمده ثبت کن؛ پس از ذخیره، پله‌های قیمت عمده را اضافه کن.")
        listing = VendorProduct(
            vendor=vendor,
            product=product,
            status=VendorProduct.Status.PENDING,
            retail_price=_strict_int(payload.get("retail_price", 0), "قیمت فروش"),
            compare_at_price=None if payload.get("compare_at_price") in (None, "") else _strict_int(payload.get("compare_at_price"), "قیمت قبل از تخفیف"),
            sale_unit=str(payload.get("sale_unit", "عدد")).strip(),
            units_per_order=_strict_int(payload.get("units_per_order", 1), "تعداد اقلام در واحد فروش"),
            stock_quantity=_strict_int(payload.get("stock_quantity", 0), "موجودی"),
            wholesale_enabled=payload.get("wholesale_enabled") is True,
            supports_custom_printing=payload.get("supports_custom_printing") is True,
            weight_grams=_strict_int(payload.get("weight_grams", 0), "وزن بسته"),
            package_length_cm=_strict_int(payload.get("package_length_cm", 0), "طول بسته"),
            package_width_cm=_strict_int(payload.get("package_width_cm", 0), "عرض بسته"),
            package_height_cm=_strict_int(payload.get("package_height_cm", 0), "ارتفاع بسته"),
            handling_days=_strict_int(payload.get("handling_days", 2), "زمان آماده‌سازی"),
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
                "retail_price", "compare_at_price", "sale_unit", "units_per_order",
                "stock_quantity", "wholesale_enabled", "supports_custom_printing",
                "weight_grams", "package_length_cm", "package_width_cm",
                "package_height_cm", "handling_days",
            }
            unknown = set(payload) - allowed
            if unknown:
                return _error("فیلدهای غیرمجاز: " + ", ".join(sorted(unknown)))
            review_required = False
            review_fields = {
                "retail_price", "compare_at_price", "sale_unit", "units_per_order",
                "wholesale_enabled", "supports_custom_printing", "weight_grams",
                "package_length_cm", "package_width_cm", "package_height_cm", "handling_days",
            }
            for field in allowed.intersection(payload):
                value = payload[field]
                if field in {"retail_price", "units_per_order", "stock_quantity", "weight_grams", "package_length_cm", "package_width_cm", "package_height_cm", "handling_days"}:
                    value = _strict_int(value, field)
                elif field == "sale_unit":
                    value = str(value or "").strip()
                elif field == "compare_at_price":
                    value = None if value in (None, "") else _strict_int(value, "قیمت قبل از تخفیف")
                elif field in {"wholesale_enabled", "supports_custom_printing"}:
                    if not isinstance(value, bool):
                        return _error(f"{field} باید true یا false باشد.")
                if field in review_fields and getattr(listing, field) != value:
                    review_required = True
                setattr(listing, field, value)
            if listing.status == VendorProduct.Status.ACTIVE and review_required:
                listing.status = VendorProduct.Status.PENDING
            listing.full_clean()
            listing.save()
        return JsonResponse({
            "ok": True,
            "listing_id": listing.id,
            "status": listing.status,
            "review_required": review_required,
            "commercial_reapproval_required": review_required,
        })
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
        if set(payload) - {"minimum_quantity", "unit_price"}:
            return _error("فقط حداقل تعداد و قیمت واحد قابل ثبت است.")
        with transaction.atomic():
            listing = get_object_or_404(
                VendorProduct.objects.select_for_update(),
                pk=listing_id,
                vendor=vendor,
            )
            if listing.status not in {VendorProduct.Status.ACTIVE, VendorProduct.Status.PENDING, VendorProduct.Status.DRAFT}:
                return _error("وضعیت فعلی محصول اجازه تغییر قیمت عمده را نمی‌دهد.", 409)
            tier = WholesalePriceTier(
                listing=listing,
                minimum_quantity=_strict_int(payload.get("minimum_quantity", 0), "حداقل تعداد عمده"),
                unit_price=_strict_int(payload.get("unit_price", 0), "قیمت واحد عمده"),
            )
            tier.full_clean()
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
@require_http_methods(["PATCH", "DELETE"])
def vendor_wholesale_tier_detail_api(request, tier_id):
    try:
        vendor = _vendor_for_user(request.user)
        with transaction.atomic():
            tier = get_object_or_404(
                WholesalePriceTier.objects.select_for_update(),
                pk=tier_id,
                listing__vendor=vendor,
            )
            listing = VendorProduct.objects.select_for_update().get(pk=tier.listing_id)
            if request.method == "DELETE":
                tier.delete()
                if not listing.wholesale_tiers.exists():
                    listing.wholesale_enabled = False
                listing.status = VendorProduct.Status.PENDING
                listing.save(update_fields=("wholesale_enabled", "status", "updated_at"))
                return JsonResponse({"ok": True, "message": "پله عمده حذف شد و تغییرات برای بررسی ارسال شد."})
            payload = _json_body(request)
            if set(payload) - {"minimum_quantity", "unit_price"} or not payload:
                return _error("فقط حداقل تعداد و قیمت واحد قابل ویرایش است.")
            if "minimum_quantity" in payload:
                tier.minimum_quantity = _strict_int(payload["minimum_quantity"], "حداقل تعداد عمده")
            if "unit_price" in payload:
                tier.unit_price = _strict_int(payload["unit_price"], "قیمت واحد عمده")
            tier.full_clean()
            tier.save()
            listing.wholesale_enabled = True
            listing.status = VendorProduct.Status.PENDING
            listing.save(update_fields=("wholesale_enabled", "status", "updated_at"))
        return JsonResponse({"ok": True, "message": "پله عمده به‌روزرسانی شد و برای بررسی ارسال شد."})
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
            tier = get_object_or_404(
                WholesalePriceTier.objects.select_for_update(),
                pk=tier_id,
                listing__vendor=vendor,
            )
            listing = VendorProduct.objects.select_for_update().get(pk=tier.listing_id)
            tier.delete()
            if not listing.wholesale_tiers.exists():
                listing.wholesale_enabled = False
            listing.status = VendorProduct.Status.PENDING
            listing.save(update_fields=("wholesale_enabled", "status", "updated_at"))
        return JsonResponse({"ok": True, "deleted": True})
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ValidationError as exc:
        return _error(exc)


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
            if locked_order.status != VendorOrder.Status.READY_TO_SHIP:
                return _error("وضعیت سفارش هنگام استعلام تغییر کرده است؛ صفحه را تازه‌سازی کن.", 409)
            active_shipment = Shipment.objects.filter(
                vendor_order=locked_order,
                status__in=[
                    Shipment.Status.QUOTED, Shipment.Status.BOOKED,
                    Shipment.Status.PICKUP_REQUESTED, Shipment.Status.HANDED_OVER,
                    Shipment.Status.IN_TRANSIT, Shipment.Status.EXCEPTION,
                ],
            ).exists()
            if active_shipment:
                return _error("برای این سفارش هم‌اکنون مرسوله فعال ثبت شده است.", 409)
            already_allocated = Shipment.objects.filter(vendor_order=locked_order).exclude(
                status=Shipment.Status.CANCELLED,
                booked_at__isnull=True,
                actual_cost__isnull=True,
            ).aggregate(total=Sum("customer_charge"))["total"] or 0
            customer_charge = max(int(locked_order.customer_shipping_amount) - int(already_allocated), 0)
            shipment = Shipment.objects.create(
                vendor_order=locked_order,
                provider=provider,
                status=Shipment.Status.QUOTED,
                quoted_cost=quote.amount,
                customer_charge=customer_charge,
                quote_reference=quote.reference,
                quote_expires_at=_parse_datetime(quote.expires_at) or (timezone.now() + timedelta(minutes=15)),
                provider_payload={
                    "quote": {
                        "reference": quote.reference,
                        "amount": quote.amount,
                        "currency": quote.currency,
                        "expires_at": quote.expires_at,
                    },
                    "request": payload,
                },
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
def manual_shipment_api(request, order_id):
    """Record a seller-arranged parcel without creating a platform carrier booking."""
    try:
        vendor_order = _vendor_order_for_user(request.user, order_id)
        if vendor_order.status != VendorOrder.Status.READY_TO_SHIP:
            return _error("ابتدا سفارش را به وضعیت «آماده ارسال» برسان.", 409)
        payload = _json_body(request)
        if set(payload) - {"carrier_name", "tracking_number"}:
            return _error("فقط نام شرکت حمل و کد رهگیری مجاز است.")
        carrier_name = " ".join(str(payload.get("carrier_name") or "").split())
        tracking_number = " ".join(str(payload.get("tracking_number") or "").split())
        if len(carrier_name) < 2 or len(carrier_name) > 120:
            return _error("نام شرکت حمل یا روش ارسال باید بین ۲ تا ۱۲۰ نویسه باشد.")
        if not tracking_number or len(tracking_number) > 160:
            return _error("کد رهگیری معتبر را وارد کن.")
        with transaction.atomic():
            locked_order = VendorOrder.objects.select_for_update().get(pk=vendor_order.pk)
            if locked_order.status != VendorOrder.Status.READY_TO_SHIP:
                return _error("وضعیت سفارش تغییر کرده است؛ صفحه را تازه‌سازی کن.", 409)
            active_shipment = Shipment.objects.filter(
                vendor_order=locked_order,
                status__in=[
                    Shipment.Status.QUOTED, Shipment.Status.BOOKED,
                    Shipment.Status.PICKUP_REQUESTED, Shipment.Status.HANDED_OVER,
                    Shipment.Status.IN_TRANSIT, Shipment.Status.EXCEPTION,
                ],
            ).exists()
            if active_shipment:
                return _error("برای این سفارش مرسوله فعال ثبت شده است.", 409)
            already_allocated = Shipment.objects.filter(vendor_order=locked_order).exclude(
                status=Shipment.Status.CANCELLED,
                booked_at__isnull=True,
                actual_cost__isnull=True,
            ).aggregate(total=Sum("customer_charge"))["total"] or 0
            customer_charge = max(int(locked_order.customer_shipping_amount) - int(already_allocated), 0)
            shipment = Shipment.objects.create(
                vendor_order=locked_order,
                provider=Shipment.Provider.MANUAL,
                status=Shipment.Status.IN_TRANSIT,
                payer=Shipment.Payer.VENDOR,
                tracking_number=tracking_number,
                customer_charge=customer_charge,
                provider_payload={"manual": True, "carrier_name": carrier_name},
            )
            locked_order.status = VendorOrder.Status.SHIPPED
            locked_order.save(update_fields=("status", "updated_at"))
        return JsonResponse({
            "ok": True,
            "shipment_id": str(shipment.uuid),
            "status": shipment.status,
            "provider": shipment.provider,
            "carrier_name": carrier_name,
            "tracking_number": shipment.tracking_number,
            "customer_charge": shipment.customer_charge,
            "message": "ارسال توسط فروشنده ثبت شد. وضعیت تحویل نهایی باید پس از دریافت مرسوله تأیید شود.",
        }, status=201)
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ValidationError as exc:
        return _error(exc)
    except (TypeError, ValueError) as exc:
        return _error(exc)


@login_required
@require_POST
def shipment_book_api(request, order_id):
    try:
        vendor_order = _vendor_order_for_user(request.user, order_id)
        payload = _json_body(request)
        shipment_uuid = payload.get("shipment_id")
        with transaction.atomic():
            # Use the same lock order as refund processing: seller order first,
            # then shipment. This prevents a booking/refund deadlock and race.
            locked_vendor_order = VendorOrder.objects.select_for_update().select_related("order", "vendor").get(
                pk=vendor_order.pk
            )
            shipment = get_object_or_404(
                Shipment.objects.select_for_update(),
                uuid=shipment_uuid,
                vendor_order=locked_vendor_order,
                status=Shipment.Status.QUOTED,
            )
            if locked_vendor_order.status != VendorOrder.Status.READY_TO_SHIP:
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
                "name": locked_vendor_order.order.shipping_recipient,
                "phone": locked_vendor_order.order.shipping_phone,
                "province": locked_vendor_order.order.shipping_province,
                "city": locked_vendor_order.order.shipping_city,
                "postal_code": locked_vendor_order.order.shipping_postal_code,
                "address": locked_vendor_order.order.shipping_address,
            },
            "order_number": locked_vendor_order.order.number,
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
            shipment.provider_payload = {
                **shipment.provider_payload,
                "booking": {
                    "external_shipment_id": result["external_shipment_id"],
                    "tracking_number": result["tracking_number"],
                    "label_url": result["label_url"],
                    "actual_cost": result.get("actual_cost"),
                },
            }
            shipment.booked_at = timezone.now()
            shipment.status = Shipment.Status.BOOKED
            shipment.last_error = ""
            shipment.save(update_fields=("external_shipment_id", "tracking_number", "label_url", "provider_payload", "booked_at", "status", "last_error", "updated_at"))
        cost_reconciliation_pending = False
        if result.get("actual_cost") is not None:
            try:
                shipment, _ = reconcile_shipment_actual_cost(
                    shipment=shipment,
                    actual_cost=result["actual_cost"],
                    actor=request.user,
                )
            except ValidationError as exc:
                cost_reconciliation_pending = True
                Shipment.objects.filter(pk=shipment.pk).update(
                    last_error=f"مرسوله ثبت شد اما تطبیق هزینه نیاز به بررسی دارد: {exc}",
                    last_event_at=timezone.now(),
                )
        return JsonResponse({
            "ok": True,
            "shipment_id": str(shipment.uuid),
            "tracking_number": shipment.tracking_number,
            "label_url": shipment.label_url,
            "status": shipment.status,
            "cost_reconciliation_pending": cost_reconciliation_pending,
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


@login_required
@require_POST
def shipment_handed_over_api(request, order_id, shipment_uuid):
    try:
        vendor_order = _vendor_order_for_user(request.user, order_id)
        with transaction.atomic():
            locked_order = VendorOrder.objects.select_for_update().get(pk=vendor_order.pk)
            shipment = get_object_or_404(
                Shipment.objects.select_for_update(),
                uuid=shipment_uuid,
                vendor_order=locked_order,
            )
            if shipment.status != Shipment.Status.BOOKED:
                return _error("فقط مرسوله ثبت‌شده و دارای کد رهگیری قابل تحویل به شرکت است.", 409)
            now = timezone.now()
            shipment.status = Shipment.Status.HANDED_OVER
            shipment.handed_over_at = now
            shipment.last_event_at = now
            shipment.save(update_fields=("status", "handed_over_at", "last_event_at", "updated_at"))
            locked_order.status = VendorOrder.Status.SHIPPED
            locked_order.save(update_fields=("status", "updated_at"))
        return JsonResponse({"ok": True, "shipment_id": str(shipment.uuid), "status": shipment.status})
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ValidationError as exc:
        return _error(exc)


@staff_member_required
@require_POST
def shipment_update_status_api(request, shipment_uuid):
    try:
        payload = _json_body(request)
        if set(payload) - {"status", "actual_cost", "delivery_evidence_reference", "delivery_evidence_note"}:
            return _error("فیلد ارسالی برای تغییر وضعیت مرسوله مجاز نیست.")
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
        shipment_ref = get_object_or_404(
            Shipment.objects.only("id", "vendor_order_id"),
            uuid=shipment_uuid,
        )
        with transaction.atomic():
            # Lock order before shipment, matching refund and booking services.
            vendor_order = VendorOrder.objects.select_for_update().select_related("vendor", "order").get(
                pk=shipment_ref.vendor_order_id
            )
            shipment = get_object_or_404(
                Shipment.objects.select_for_update(),
                uuid=shipment_uuid,
                vendor_order=vendor_order,
            )
            transitions = {
                Shipment.Status.BOOKED: {
                    Shipment.Status.IN_TRANSIT, Shipment.Status.DELIVERED,
                    Shipment.Status.DELIVERY_FAILED, Shipment.Status.EXCEPTION,
                },
                Shipment.Status.HANDED_OVER: {
                    Shipment.Status.IN_TRANSIT, Shipment.Status.DELIVERED,
                    Shipment.Status.DELIVERY_FAILED, Shipment.Status.EXCEPTION,
                },
                Shipment.Status.IN_TRANSIT: {
                    Shipment.Status.DELIVERED, Shipment.Status.DELIVERY_FAILED,
                    Shipment.Status.RETURNED, Shipment.Status.EXCEPTION,
                },
                Shipment.Status.DELIVERY_FAILED: {
                    Shipment.Status.IN_TRANSIT, Shipment.Status.DELIVERED,
                    Shipment.Status.RETURNED, Shipment.Status.EXCEPTION,
                },
                Shipment.Status.EXCEPTION: {
                    Shipment.Status.IN_TRANSIT, Shipment.Status.DELIVERED,
                    Shipment.Status.DELIVERY_FAILED, Shipment.Status.RETURNED,
                },
                Shipment.Status.DELIVERED: {Shipment.Status.RETURNED, Shipment.Status.EXCEPTION},
            }
            if target not in transitions.get(shipment.status, set()):
                return _error("تغییر وضعیت مرسوله با گردش فعلی سازگار نیست.", 409)
            now = timezone.now()
            shipment.status = target
            shipment.last_event_at = now
            if target == Shipment.Status.DELIVERED:
                evidence_reference = " ".join(str(payload.get("delivery_evidence_reference") or "").split())
                evidence_note = " ".join(str(payload.get("delivery_evidence_note") or "").split())
                if not evidence_reference or len(evidence_reference) > 180:
                    return _error(
                        "برای تأیید تحویل، مرجع قابل پیگیری از پنل شرکت حمل یا تأیید گیرنده را وارد کن.",
                        400,
                    )
                if len(evidence_note) > 1000:
                    return _error("توضیح مدرک تحویل حداکثر ۱۰۰۰ نویسه باشد.", 400)
                shipment.delivered_at = now
                shipment.provider_payload = {
                    **(shipment.provider_payload or {}),
                    "delivery_confirmation": {
                        "source": "staff_manual",
                        "reference": evidence_reference,
                        "note": evidence_note,
                        "confirmed_by_user_id": request.user.pk,
                        "confirmed_at": now.isoformat(),
                    },
                }
            if target == Shipment.Status.RETURNED:
                vendor_order.status = VendorOrder.Status.DISPUTED
                vendor_order.save(update_fields=("status", "updated_at"))
            shipment.save(update_fields=("status", "last_event_at", "delivered_at", "provider_payload", "updated_at"))
            if payload.get("actual_cost") is not None:
                reconcile_shipment_actual_cost(
                    shipment=shipment,
                    actual_cost=payload["actual_cost"],
                    actor=request.user,
                )
                shipment.refresh_from_db()
            if target == Shipment.Status.DELIVERED:
                # Only complete the seller order after every parcel has a
                # confirmed delivered state.
                all_parcels_delivered = not Shipment.objects.filter(
                    vendor_order=vendor_order,
                ).exclude(status=Shipment.Status.DELIVERED).exists()
                if all_parcels_delivered:
                    mark_vendor_order_delivered(vendor_order, delivered_at=now)
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
def order_refund_api(request, order_uuid):
    """Record a refund only after staff confirms the external refund actually succeeded."""
    try:
        payload = _json_body(request)
        order = get_object_or_404(Order, uuid=order_uuid)
        entry, created = record_full_order_refund(
            order=order,
            refund_reference=str(payload.get("refund_reference", "")),
            refund_confirmed=payload.get("refund_confirmed") is True,
            actual_refund_amount=payload.get("actual_refund_amount"),
            refund_source=str(payload.get("refund_source", "bank")),
            actor=request.user,
        )
        return JsonResponse({
            "ok": True,
            "created": created,
            "journal_entry_id": entry.id,
            "idempotency_key": entry.idempotency_key,
            "status": entry.status,
            "message": "بازپرداخت قطعی در حسابداری ثبت شد؛ این API خودش پولی به مشتری واریز نمی‌کند.",
        })
    except (ValidationError, TypeError, ValueError) as exc:
        return _error(exc)


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
            actual_amount=payload.get("actual_amount"),
            actor=request.user,
        )
        return JsonResponse({"ok": True, "batch_id": batch.id, "status": batch.status, "payout_reference": batch.payout_reference})
    except (PermissionDenied, ValidationError) as exc:
        return _error(exc, 403 if isinstance(exc, PermissionDenied) else 409)
