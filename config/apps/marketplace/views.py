from __future__ import annotations

import json
import os
from datetime import timedelta

from PIL import Image, UnidentifiedImageError

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Min, Prefetch, Q, Sum
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .carriers import CarrierError, CarrierNotConfigured, get_carrier, validate_quote_input
from apps.orders.models import Cart, CartItem, Order
from apps.users.models import Address, City, Province, RoleUser, User
from apps.shop.models import Category, Product, ProductImage
from .models import CategoryRequest, FinancialReconciliation, JournalEntry, SettlementBatch, Shipment, Vendor, VendorApplication, VendorOrder, VendorProduct, VendorProductSubmission, WholesalePriceTier
from .services import _strict_int, approve_settlement, create_shipping_quote, mark_vendor_order_delivered, reconcile_shipment_actual_cost, record_carrier_invoice_payment, record_external_reconciliation, record_full_order_refund, record_gateway_settlement, record_payout_result, trial_balance
from .payouts import PayoutError, PayoutNotConfigured, submit_settlement_payout


SELLABLE_UNIT_COUNTS = {1, 2, 3, 4, 6, 12, 24, 36, 48, 72, 144}
FIXED_SALE_UNITS = {"عدد": 1, "جفت": 2, "جین": 12}
ALLOWED_SALE_UNITS = set(FIXED_SALE_UNITS) | {"بسته", "کارتن"}


def _validate_sale_pack(sale_unit, units_per_order):
    unit = " ".join(str(sale_unit or "").split())
    if unit not in ALLOWED_SALE_UNITS:
        raise ValidationError({"sale_unit": "واحد فروش را از فهرست انتخاب کن."})
    try:
        count = int(units_per_order)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"units_per_order": "اندازه واحد فروش معتبر نیست."}) from exc
    if count not in SELLABLE_UNIT_COUNTS:
        raise ValidationError({"units_per_order": "اندازه بسته را از فهرست انتخاب کن."})
    fixed_count = FIXED_SALE_UNITS.get(unit)
    if fixed_count is not None and count != fixed_count:
        raise ValidationError({"units_per_order": f"واحد «{unit}» باید دقیقاً شامل {fixed_count} قلم باشد."})
    return unit, count


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


@require_http_methods(["GET", "POST"])
def vendor_application_page(request):
    """Accept prospective seller applications before an account is created."""
    existing = None
    if request.user.is_authenticated:
        existing = VendorApplication.objects.filter(user=request.user).first()
    else:
        application_id = request.session.get("vendor_application_id")
        if application_id:
            existing = VendorApplication.objects.filter(pk=application_id).first()
    if request.method == "POST":
        if existing and existing.status in {VendorApplication.Status.PENDING, VendorApplication.Status.APPROVED}:
            messages.info(request, "درخواست فروشندگی شما قبلاً ثبت شده است؛ وضعیت آن را در همین صفحه ببین.")
            return redirect("marketplace:vendor_application_page")
        payload = {
            "user": request.user,
            "contact_name": str(request.POST.get("contact_name") or "").strip(),
            "contact_email": str(request.POST.get("contact_email") or getattr(request.user, "email", "") or "").strip(),
            "contact_phone": str(request.POST.get("contact_phone") or getattr(request.user, "phone", "") or "").strip(),
            "national_id": str(request.POST.get("national_id") or "").strip(),
            "store_name": str(request.POST.get("store_name") or "").strip(),
            "seller_type": str(request.POST.get("seller_type") or "").strip(),
            "province": str(request.POST.get("province") or "").strip(),
            "city": str(request.POST.get("city") or "").strip(),
            "postal_code": str(request.POST.get("postal_code") or "").strip(),
            "address": str(request.POST.get("address") or "").strip(),
            "website_or_social": str(request.POST.get("website_or_social") or "").strip(),
            "description": str(request.POST.get("description") or "").strip(),
        }
        try:
            payload["contact_phone"] = str(User.objects.normalize_phone(payload["contact_phone"]))
        except ValueError:
            return render(request, "marketplace/vendor_application.html", {
                "application": existing,
                "errors": ["شماره تماس معتبر نیست؛ شماره تلفن همراه ایران را وارد کن."],
                "form_data": request.POST,
            }, status=400)
        if not existing:
            duplicate = VendorApplication.objects.filter(status__in=[VendorApplication.Status.PENDING, VendorApplication.Status.APPROVED]).filter(
                contact_phone=payload["contact_phone"]
            ).first()
            if duplicate:
                return render(request, "marketplace/vendor_application.html", {
                    "application": None,
                    "errors": ["برای این شماره تماس درخواست در انتظار بررسی وجود دارد."],
                    "form_data": request.POST,
                }, status=400)
            if payload["contact_email"]:
                duplicate = VendorApplication.objects.filter(
                    status__in=[VendorApplication.Status.PENDING, VendorApplication.Status.APPROVED],
                    contact_email__iexact=payload["contact_email"],
                ).first()
                if duplicate:
                    return render(request, "marketplace/vendor_application.html", {
                        "application": None,
                        "errors": ["برای این ایمیل درخواست در انتظار بررسی وجود دارد."],
                        "form_data": request.POST,
                    }, status=400)
        application = existing or VendorApplication(
            user=request.user if request.user.is_authenticated else None
        )
        for key, value in payload.items():
            if key != "user":
                setattr(application, key, value)
        application.status = VendorApplication.Status.PENDING
        application.reviewer_note = ""
        application.reviewed_by = None
        application.reviewed_at = None
        try:
            with transaction.atomic():
                application.full_clean()
                application.save()
        except IntegrityError:
            return render(request, "marketplace/vendor_application.html", {
                "application": existing,
                "errors": ["این درخواست با اطلاعات مشابه هم‌زمان ثبت شده است؛ صفحه را تازه‌سازی و وضعیت درخواست را بررسی کن."],
                "form_data": request.POST,
            }, status=409)
        except ValidationError as exc:
            errors = []
            for field, field_errors in getattr(exc, "message_dict", {}).items():
                errors.extend([f"{field}: {message}" for message in field_errors])
            if not errors:
                errors = list(exc.messages)
            return render(request, "marketplace/vendor_application.html", {
                "application": existing, "errors": errors, "form_data": request.POST,
            }, status=400)
        if not request.user.is_authenticated:
            request.session["vendor_application_id"] = application.pk
        messages.success(request, "درخواست فروشندگی ثبت شد. پس از بررسی مدیر، در صورت تأیید حساب کاربری توسط مدیر ایجاد می‌شود؛ این فرم دسترسی فروشندگی ایجاد نمی‌کند.")
        return redirect("marketplace:vendor_application_page")
    return render(request, "marketplace/vendor_application.html", {
        "application": existing, "form_data": {}, "errors": [],
    })


@require_GET
def marketplace_storefront_page(request):
    """Public discovery page for seller-owned listings, distinct from platform catalog pricing."""
    listings = VendorProduct.objects.filter(
        status=VendorProduct.Status.ACTIVE,
        vendor__status=Vendor.Status.ACTIVE,
        vendor__user__is_active=True,
        stock_quantity__gt=0,
        product__is_active=True,
        product__category__is_active=True,
    ).annotate(
        minimum_wholesale_quantity=Min("wholesale_tiers__minimum_quantity"),
    ).filter(
        Q(sale_type__in=[VendorProduct.SaleType.RETAIL, VendorProduct.SaleType.BOTH])
        | Q(stock_quantity__gte=F("minimum_wholesale_quantity"))
    ).select_related("vendor", "product", "product__category").prefetch_related(
        Prefetch(
            "product__images",
            queryset=ProductImage.objects.order_by("sort_order", "id"),
            to_attr="marketplace_images",
        ),
        "wholesale_tiers",
    )
    query = str(request.GET.get("q") or "").strip()[:100]
    if query:
        listings = listings.filter(
            Q(product__name__icontains=query)
            | Q(vendor__store_name__icontains=query)
            | Q(product__short_description__icontains=query)
        )
    category_slug = str(request.GET.get("category") or "").strip()
    if category_slug:
        listings = listings.filter(product__category__slug=category_slug)
    sale_type = str(request.GET.get("sale_type") or "").strip()
    if sale_type in VendorProduct.SaleType.values:
        listings = listings.filter(sale_type=sale_type)
    sort = str(request.GET.get("sort") or "newest")
    sort_map = {
        "newest": ("-created_at", "id"),
        "price_asc": ("retail_price", "id"),
        "price_desc": ("-retail_price", "id"),
        "store": ("vendor__store_name", "product__name"),
    }
    listings = listings.order_by(*sort_map.get(sort, sort_map["newest"]))
    page_obj = Paginator(listings, 12).get_page(request.GET.get("page"))
    return render(request, "marketplace/storefront.html", {
        "listings": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": page_obj.paginator,
        "categories": Category.objects.filter(is_active=True).order_by("name"),
        "query": query,
        "filter_category": category_slug,
        "filter_sale_type": sale_type,
        "filter_sort": sort,
        "result_count": page_obj.paginator.count,
    })


PORTAL_SECTIONS = {
    "seller-dashboard": ("داشبورد فروشنده", "seller", "نمای کلی فروش، سفارش‌ها و تسویه‌ها."),
    "new-product": ("ثبت محصول جدید", "seller", "ثبت کالای جدید و تعیین قیمت، موجودی و شرایط عمده در پنل فروشنده."),
    "my-products": ("محصولات من", "seller", "مدیریت آگهی‌ها، قیمت، موجودی و وضعیت تأیید محصولات."),
    "orders-shipping": ("سفارش‌ها و ارسال", "seller", "مدیریت سفارش‌ها، ثبت ارسال و رهگیری مرسوله."),
    "vendor-settlements": ("تسویه‌های من", "seller", "مشاهده تسویه‌ها، مبالغ قابل پرداخت و سوابق پرداخت."),
    "bank-profile": ("اطلاعات بانکی", "seller", "ثبت و پیگیری تأیید حساب بانکی فروشنده."),
    "shipping-profile": ("مبدأ ارسال", "seller", "تنظیم نشانی، کد پستی و اطلاعات تماس مبدأ ارسال."),
    "accounting-overview": ("نمای کلی حسابداری", "admin", "خلاصه مالی، دفترکل و وضعیت ثبت‌های حسابداری."),
    "trial-balance": ("تراز آزمایشی", "admin", "بررسی توازن بدهکار و بستانکار دفترکل."),
    "reconciliation": ("مغایرت‌گیری", "admin", "ثبت و بررسی مغایرت‌های بانکی و مالی."),
    "gateway-settlement": ("تسویه درگاه", "admin", "ثبت و تطبیق تسویه‌های درگاه پرداخت."),
    "carrier-payment": ("پرداخت شرکت حمل", "admin", "ثبت هزینه واقعی حمل و پرداخت به شرکت‌های حمل."),
    "settlement-queue": ("صف تسویه فروشندگان", "admin", "بررسی، تأیید و ثبت نتیجه پرداخت تسویه فروشندگان."),
}


@login_required
@require_GET
def portal_section_page(request, section):
    config = PORTAL_SECTIONS.get(section)
    if not config:
        return HttpResponseForbidden("این بخش تعریف نشده است.")
    title, audience, description = config
    if audience == "admin":
        if not (request.user.is_staff or request.user.is_superuser):
            return HttpResponseForbidden("دسترسی این بخش فقط برای مدیران مجاز است.")
        admin_anchors = {
            "trial-balance": "ma-trial-balance",
            "reconciliation": "ma-reconciliation",
            "gateway-settlement": "ma-gateway",
            "carrier-payment": "ma-carrier-payment",
            "settlement-queue": "ma-settlement-queue",
            "accounting-overview": "ma-overview",
        }
        if section != "accounting-overview":
            anchor = admin_anchors.get(section, "ma-overview")
            return redirect(f"{reverse('marketplace:portal_section_page', kwargs={'section': 'accounting-overview'})}#{anchor}")
        providers = {}
        for prefix, label in (("TIPAX", "تیپاکس"), ("POST", "شرکت ملی پست")):
            providers[prefix.lower()] = {
                "label": label,
                "base_url": bool(os.environ.get(f"{prefix}_API_BASE_URL", "").strip()),
                "token": bool(os.environ.get(f"{prefix}_API_TOKEN", "").strip()),
                "quote_path": bool(os.environ.get(f"{prefix}_QUOTE_PATH", "").strip()),
                "quote_amount_path": bool(os.environ.get(f"{prefix}_QUOTE_AMOUNT_PATH", "").strip()),
                "quote_currency_path": bool(os.environ.get(f"{prefix}_QUOTE_CURRENCY_PATH", "").strip()),
                "amount_divisor": bool(os.environ.get(f"{prefix}_AMOUNT_DIVISOR", "").strip()),
                "shipment_path": bool(os.environ.get(f"{prefix}_SHIPMENT_PATH", "").strip()),
                "tracking_path": bool(os.environ.get(f"{prefix}_TRACKING_PATH", "").strip()),
            }
        payout_config = {
            "base_url": bool(os.environ.get("PAYOUT_API_BASE_URL", "").strip()),
            "token": bool(os.environ.get("PAYOUT_API_TOKEN", "").strip()),
            "path": bool(os.environ.get("PAYOUT_API_PATH", "").strip()),
            "amount_multiplier": bool(os.environ.get("PAYOUT_AMOUNT_MULTIPLIER", "").strip()),
            "currency": bool(os.environ.get("PAYOUT_API_CURRENCY", "").strip()),
            "reference_path": bool(os.environ.get("PAYOUT_RESPONSE_REFERENCE_PATH", "").strip()),
            "status_path": bool(os.environ.get("PAYOUT_RESPONSE_STATUS_PATH", "").strip()),
            "amount_path": bool(os.environ.get("PAYOUT_RESPONSE_AMOUNT_PATH", "").strip()),
            "currency_path": bool(os.environ.get("PAYOUT_RESPONSE_CURRENCY_PATH", "").strip()),
        }
        cutoff = timezone.now() - timedelta(days=30)
        vendor_summary = {}
        recent_vendor_orders = VendorOrder.objects.filter(
            created_at__gte=cutoff,
        ).exclude(status=VendorOrder.Status.CANCELLED).select_related("vendor").only(
            "vendor_id", "vendor__store_name", "subtotal", "status", "vendor_payable",
        )
        for row in recent_vendor_orders:
            summary = vendor_summary.setdefault(row.vendor_id, {
                "store_name": row.vendor.store_name,
                "sales": 0,
                "orders": 0,
                "delivered": 0,
                "in_progress": 0,
            })
            summary["sales"] += int(row.subtotal or 0)
            summary["orders"] += 1
            if row.status == VendorOrder.Status.DELIVERED:
                summary["delivered"] += 1
            elif row.status not in {VendorOrder.Status.CANCELLED, VendorOrder.Status.DISPUTED}:
                summary["in_progress"] += 1
        vendor_sales_summary = sorted(
            vendor_summary.values(),
            key=lambda item: (item["sales"], item["orders"]),
            reverse=True,
        )[:20]
        return render(request, "marketplace/admin_accounting.html", {
            "section": section,
            "section_title": title,
            "section_description": description,
            "carrier_providers": providers,
            "payout_config": payout_config,
            "vendor_sales_summary": vendor_sales_summary,
        })
    try:
        _vendor_for_user(request.user)
    except PermissionDenied as exc:
        return HttpResponseForbidden(str(exc))
    seller_anchors = {
        "seller-dashboard": "vd-overview",
        "new-product": "vd-new-product-section",
        "my-products": "vd-products-section",
        "orders-shipping": "vd-orders-section",
        "vendor-settlements": "vd-settlements-section",
        "bank-profile": "vd-financial-section",
        "shipping-profile": "vd-shipping-section",
    }
    anchor = seller_anchors.get(section, "vd-overview")
    return redirect(f"{reverse('marketplace:vendor_dashboard_page')}#{anchor}")


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
    if not is_store_manager:
        raise PermissionDenied(
            f"برای این حساب دسترسی فروشندگی فعال نیست؛ نقش ذخیره‌شده "
            f"({role_value or 'خالی'}) مدیر فروشگاه نیست."
        )
    if VendorApplication.objects.filter(
        user=user,
        status=VendorApplication.Status.REJECTED,
    ).exists():
        raise PermissionDenied("درخواست فروشندگی این حساب رد شده است؛ مدیر باید ابتدا وضعیت درخواست را اصلاح کند.")
    application = VendorApplication.objects.filter(
        user=user,
        status=VendorApplication.Status.APPROVED,
    ).first()
    try:
        vendor = Vendor.objects.get(user=user)
        changed_fields = []
        # An approved application carries the seller's reviewed retail/wholesale scope.
        if application and vendor.seller_type != application.seller_type:
            vendor.seller_type = application.seller_type
            changed_fields.append("seller_type")
        if application and vendor.store_name != application.store_name:
            vendor.store_name = application.store_name
            changed_fields.append("store_name")
        # The manually assigned store_manager role is the administrator's approval
        # gate. A pending profile left by an earlier release is activated here;
        # suspended/rejected profiles are never silently reactivated.
        if vendor.status == Vendor.Status.PENDING:
            vendor.status = Vendor.Status.ACTIVE
            vendor.approved_at = timezone.now()
            changed_fields.extend(("status", "approved_at"))
        if changed_fields:
            vendor.save(update_fields=tuple(set(changed_fields) | {"updated_at"}))
        return vendor
    except Vendor.DoesNotExist:
        display_name = (application.store_name if application else user.get_full_name()).strip() or f"فروشگاه {user.pk}"
        vendor, _ = Vendor.objects.get_or_create(
            user=user,
            defaults={
                "store_name": display_name[:160],
                "slug": f"store-{user.pk}-{user.uuid.hex[:8]}",
                "seller_type": application.seller_type if application else Vendor.SellerType.RETAIL,
                "status": Vendor.Status.ACTIVE,
                "approved_at": timezone.now(),
            },
        )
        return vendor



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
    selected_city = City.objects.select_related("province").filter(
        name=vendor.pickup_city, province__name=vendor.pickup_province
    ).first()
    selected_province_id = selected_city.province_id if selected_city else ""
    selected_city_id = selected_city.pk if selected_city else ""
    return render(request, "marketplace/vendor_dashboard.html", {
        "vendor": vendor,
        "provinces": Province.objects.order_by("name"),
        "cities": City.objects.select_related("province").order_by("name"),
        "selected_province_id": selected_province_id,
        "selected_city_id": selected_city_id,
    })


@login_required
@require_POST
def vendor_shipping_profile_api(request):
    try:
        vendor = _vendor_for_user(request.user)
        payload = _json_body(request)
        allowed = {"pickup_postal_code", "pickup_address", "pickup_city", "pickup_province", "pickup_city_id", "pickup_province_id", "contact_phone"}
        if set(payload) - allowed:
            return _error("فقط اطلاعات مبدأ ارسال قابل ویرایش است.")
        postal = str(payload.get("pickup_postal_code", vendor.pickup_postal_code)).strip()
        if postal and (len(postal) != 10 or not postal.isdigit()):
            return _error("کد پستی مبدأ باید ۱۰ رقم باشد.")
        updates = set()
        if "pickup_city_id" in payload or "pickup_province_id" in payload:
            city_id = payload.get("pickup_city_id")
            province_id = payload.get("pickup_province_id")
            if not city_id or not province_id:
                return _error("استان و شهر مبدأ را از فهرست انتخاب کن.")
            city = City.objects.select_related("province").filter(
                pk=city_id, province_id=province_id
            ).first()
            if city is None:
                return _error("شهر انتخاب‌شده با استان انتخابی مطابقت ندارد.")
            vendor.pickup_city = city.name
            vendor.pickup_province = city.province.name
            updates.update(("pickup_city", "pickup_province"))
        else:
            # Compatibility with existing clients; the new form always submits
            # validated IDs from the canonical Province/City tables.
            for field in ("pickup_city", "pickup_province"):
                if field in payload:
                    setattr(vendor, field, str(payload[field] or "").strip())
                    updates.add(field)
        for field in ("pickup_postal_code", "pickup_address", "contact_phone"):
            if field in payload:
                setattr(vendor, field, str(payload[field] or "").strip())
                updates.add(field)
        vendor.save(update_fields=tuple(updates) + ("updated_at",))
        return JsonResponse({
            "ok": True,
            "pickup_postal_code": vendor.pickup_postal_code,
            "pickup_city": vendor.pickup_city,
            "pickup_province": vendor.pickup_province,
            "message": "اطلاعات مبدأ ارسال ذخیره شد.",
        })
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
    # Amount already in a settlement batch, including failed batches that need staff review.
    payable = sum(
        batch.payable_amount for batch in vendor.settlements.filter(
            status__in=[
                SettlementBatch.Status.PENDING_APPROVAL,
                SettlementBatch.Status.APPROVED,
                SettlementBatch.Status.PROCESSING,
                SettlementBatch.Status.FAILED,
            ]
        )
    )
    # Also include matured delivered orders not yet included in an active/paid/failed batch.
    # Mirror the settlement service's conservative shipping eligibility checks.
    eligible_orders = VendorOrder.objects.filter(
        vendor=vendor,
        status=VendorOrder.Status.DELIVERED,
        settlement_eligible_at__lte=timezone.now(),
        vendor_payable__gt=0,
    ).exclude(settlement_lines__batch__status__in=[
        SettlementBatch.Status.PENDING_APPROVAL,
        SettlementBatch.Status.APPROVED,
        SettlementBatch.Status.PROCESSING,
        SettlementBatch.Status.PAID,
        SettlementBatch.Status.FAILED,
    ]).prefetch_related("shipments").distinct()
    for vendor_order in eligible_orders:
        shipments = list(vendor_order.shipments.all())
        if not shipments or any(shipment.status != Shipment.Status.DELIVERED for shipment in shipments):
            continue
        if any(
            shipment.payer == Shipment.Payer.PLATFORM and shipment.actual_cost is None
            for shipment in shipments
        ):
            continue
        if any(shipment.payer == Shipment.Payer.RECIPIENT for shipment in shipments):
            continue
        if sum(int(shipment.customer_charge or 0) for shipment in shipments) > int(vendor_order.customer_shipping_amount):
            continue
        payable += int(vendor_order.vendor_payable) + sum(
            int(shipment.customer_charge or 0)
            for shipment in shipments
            if shipment.payer == Shipment.Payer.VENDOR
        )
    paid = sum(batch.payable_amount for batch in vendor.settlements.filter(status=SettlementBatch.Status.PAID))

    # Real seller sales reporting, derived from immutable paid-order snapshots.
    sales_since = timezone.now() - timedelta(days=30)
    recent_orders = list(
        orders.filter(created_at__gte=sales_since)
        .exclude(status=VendorOrder.Status.CANCELLED)
        .only("subtotal", "items_snapshot", "status")
    )
    sales_30d = sum(int(row.subtotal or 0) for row in recent_orders)
    sold_units_30d = 0
    products = {}
    for row in recent_orders:
        snapshot = row.items_snapshot if isinstance(row.items_snapshot, list) else []
        snapshot_gross = sum(
            int(item.get("line_total") or 0)
            for item in snapshot if isinstance(item, dict)
        )
        # Distribute order-level discounts proportionally so product revenue
        # reconciles to the actual vendor-order subtotal.
        remaining_revenue = int(row.subtotal or 0)
        remaining_gross = snapshot_gross
        for index, item in enumerate(snapshot):
            if not isinstance(item, dict):
                continue
            quantity = max(0, int(item.get("quantity") or 0))
            gross = max(0, int(item.get("line_total") or 0))
            sold_units_30d += quantity
            if remaining_gross <= 0:
                allocated = 0
            elif index == len(snapshot) - 1:
                allocated = remaining_revenue
            else:
                allocated = min(remaining_revenue, gross * int(row.subtotal or 0) // snapshot_gross)
            remaining_revenue -= allocated
            remaining_gross -= gross
            key = str(item.get("vendor_product_id") or item.get("product_id") or item.get("product_name") or "unknown")
            entry = products.setdefault(key, {
                "name": str(item.get("product_name") or "محصول بدون نام"),
                "quantity": 0,
                "revenue": 0,
            })
            entry["quantity"] += quantity
            entry["revenue"] += allocated
    top_products = sorted(products.values(), key=lambda item: (item["quantity"], item["revenue"]), reverse=True)[:5]

    return JsonResponse({
        "ok": True,
        "vendor": {"id": vendor.id, "store_name": vendor.store_name, "status": vendor.status},
        "orders": {"pending_fulfilment": pending, "delivered": delivered, "total": orders.count()},
        "sales": {"last_30_days": sales_30d, "sold_units_last_30_days": sold_units_30d, "top_products": top_products},
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
                    "sale_type": item.sale_type,
                    "wholesale_minimum_quantity": item.wholesale_minimum_quantity,
                    "wholesale_unit_price": item.wholesale_unit_price,
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
            "sale_type", "wholesale_minimum_quantity", "wholesale_unit_price", "csrfmiddlewaretoken",
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
        sale_type = request.POST.get("sale_type", VendorProductSubmission.SaleType.RETAIL).strip()
        if sale_type not in VendorProductSubmission.SaleType.values:
            return _error("نوع فروش معتبر نیست.")
        if sale_type in {VendorProductSubmission.SaleType.WHOLESALE, VendorProductSubmission.SaleType.BOTH} and vendor.seller_type == Vendor.SellerType.RETAIL:
            return _error("این فروشگاه مجوز فروش عمده ندارد.", 403)
        wholesale_minimum = int(request.POST.get("wholesale_minimum_quantity", 0) or 0)
        wholesale_price = int(request.POST.get("wholesale_unit_price", 0) or 0)
        if sale_type in {VendorProductSubmission.SaleType.WHOLESALE, VendorProductSubmission.SaleType.BOTH} and wholesale_minimum not in SELLABLE_UNIT_COUNTS:
            return _error("حداقل تعداد عمده را از فهرست انتخاب کن.")
        try:
            sale_unit, units_per_order = _validate_sale_pack(
                request.POST.get("sale_unit", "عدد"),
                request.POST.get("units_per_order", 1),
            )
        except ValidationError as exc:
            return _error(exc)
        submission = VendorProductSubmission(
            vendor=vendor,
            category=category,
            name=request.POST.get("name", "").strip(),
            short_description=strip_tags(request.POST.get("short_description", "")).strip(),
            description=strip_tags(request.POST.get("description", "")).strip(),
            image=image,
            retail_price=int(request.POST.get("retail_price", 0)),
            compare_at_price=int(compare_value) if compare_value else None,
            sale_type=sale_type,
            wholesale_minimum_quantity=wholesale_minimum if sale_type in {VendorProductSubmission.SaleType.WHOLESALE, VendorProductSubmission.SaleType.BOTH} else None,
            wholesale_unit_price=wholesale_price if sale_type in {VendorProductSubmission.SaleType.WHOLESALE, VendorProductSubmission.SaleType.BOTH} else None,
            sale_unit=sale_unit,
            units_per_order=units_per_order,
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
            "sale_type": listing.sale_type,
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
            "stock_quantity", "wholesale_enabled", "sale_type", "wholesale_minimum_quantity",
            "wholesale_unit_price", "supports_custom_printing", "weight_grams",
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
        sale_type = str(payload.get("sale_type", "retail")).strip()
        if sale_type not in VendorProduct.SaleType.values:
            return _error("نوع فروش را از بین تکی، عمده یا تکی و عمده انتخاب کن.")
        if sale_type in {VendorProduct.SaleType.WHOLESALE, VendorProduct.SaleType.BOTH} and vendor.seller_type == Vendor.SellerType.RETAIL:
            return _error("این فروشگاه مجوز فروش عمده ندارد.", 403)
        if payload.get("wholesale_enabled") is True:
            return _error("برای ثبت فروش عمده از فیلدهای نوع فروش و قیمت عمده استفاده کن.")
        wholesale_minimum = _strict_int(payload.get("wholesale_minimum_quantity", 0), "حداقل تعداد عمده") if sale_type in {VendorProduct.SaleType.WHOLESALE, VendorProduct.SaleType.BOTH} else 0
        wholesale_price = _strict_int(payload.get("wholesale_unit_price", 0), "قیمت واحد عمده") if sale_type in {VendorProduct.SaleType.WHOLESALE, VendorProduct.SaleType.BOTH} else 0
        if sale_type in {VendorProduct.SaleType.WHOLESALE, VendorProduct.SaleType.BOTH} and wholesale_minimum not in SELLABLE_UNIT_COUNTS:
            return _error("حداقل تعداد عمده را از فهرست انتخاب کن.")
        if sale_type in {VendorProduct.SaleType.WHOLESALE, VendorProduct.SaleType.BOTH} and (wholesale_minimum < 1 or wholesale_price < 1):
            return _error("برای فروش عمده، حداقل یک واحد فروش و قیمت واحد عمده را وارد کن.")
        try:
            sale_unit, units_per_order = _validate_sale_pack(
                payload.get("sale_unit", "عدد"),
                payload.get("units_per_order", 1),
            )
        except ValidationError as exc:
            return _error(exc)
        retail_price = _strict_int(payload.get("retail_price", 0), "قیمت فروش")
        if wholesale_price and wholesale_price > retail_price:
            return _error("قیمت واحد عمده نباید از قیمت تکی بیشتر باشد.")
        listing = VendorProduct(
            vendor=vendor,
            product=product,
            status=VendorProduct.Status.PENDING,
            sale_type=sale_type,
            retail_price=retail_price,
            compare_at_price=None if payload.get("compare_at_price") in (None, "") else _strict_int(payload.get("compare_at_price"), "قیمت قبل از تخفیف"),
            sale_unit=sale_unit,
            units_per_order=units_per_order,
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
        with transaction.atomic():
            listing.save()
            if sale_type in {VendorProduct.SaleType.WHOLESALE, VendorProduct.SaleType.BOTH}:
                tier = WholesalePriceTier(
                    listing=listing,
                    minimum_quantity=wholesale_minimum,
                    unit_price=wholesale_price,
                )
                tier.full_clean()
                tier.save()
                listing.wholesale_enabled = True
                listing.save(update_fields=("wholesale_enabled", "updated_at"))
        return JsonResponse({"ok": True, "listing_id": listing.id, "status": listing.status, "sale_type": listing.sale_type, "message": "محصول و شرایط فروش برای بررسی مدیر ثبت شد."}, status=201)
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
                "retail_price", "compare_at_price", "sale_type", "sale_unit", "units_per_order",
                "stock_quantity", "supports_custom_printing",
                "weight_grams", "package_length_cm", "package_width_cm",
                "package_height_cm", "handling_days",
            }
            unknown = set(payload) - allowed
            if unknown:
                return _error("فیلدهای غیرمجاز: " + ", ".join(sorted(unknown)))
            if "sale_unit" in payload or "units_per_order" in payload:
                candidate_unit = payload.get("sale_unit", listing.sale_unit)
                candidate_count = payload.get("units_per_order", listing.units_per_order)
                if str(candidate_unit).strip() != listing.sale_unit or str(candidate_count) != str(listing.units_per_order):
                    try:
                        payload["sale_unit"], payload["units_per_order"] = _validate_sale_pack(
                            candidate_unit,
                            candidate_count,
                        )
                    except ValidationError as exc:
                        return _error(exc)
                else:
                    # Preserve unchanged legacy units so sellers can still update stock/price.
                    payload["sale_unit"] = listing.sale_unit
                    payload["units_per_order"] = listing.units_per_order
            review_required = False
            review_fields = {
                "retail_price", "compare_at_price", "sale_type", "sale_unit", "units_per_order",
                "supports_custom_printing", "weight_grams",
                "package_length_cm", "package_width_cm", "package_height_cm", "handling_days",
            }
            for field in allowed.intersection(payload):
                value = payload[field]
                if field in {"retail_price", "units_per_order", "stock_quantity", "weight_grams", "package_length_cm", "package_width_cm", "package_height_cm", "handling_days"}:
                    value = _strict_int(value, field)
                elif field == "sale_type":
                    value = str(value or "").strip()
                    if value not in VendorProduct.SaleType.values:
                        return _error("نوع فروش را از فهرست انتخاب کن.")
                    if value in {VendorProduct.SaleType.WHOLESALE, VendorProduct.SaleType.BOTH} and vendor.seller_type == Vendor.SellerType.RETAIL:
                        return _error("این فروشگاه مجوز فروش عمده ندارد.", 403)
                    if value in {VendorProduct.SaleType.WHOLESALE, VendorProduct.SaleType.BOTH} and not listing.wholesale_tiers.exists():
                        return _error("ابتدا حداقل یک پله قیمت عمده ثبت کن.")
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
            if listing.sale_type == VendorProduct.SaleType.RETAIL:
                listing.wholesale_enabled = False
            elif listing.sale_type in {VendorProduct.SaleType.WHOLESALE, VendorProduct.SaleType.BOTH}:
                listing.wholesale_enabled = True
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
def vendor_product_archive_api(request, listing_id):
    """Soft-remove a listing only when it has no order awaiting fulfilment."""
    try:
        vendor = _vendor_for_user(request.user)
        with transaction.atomic():
            listing = get_object_or_404(
                VendorProduct.objects.select_for_update(),
                pk=listing_id,
                vendor=vendor,
            )
            active_orders = vendor.orders.exclude(
                status__in=[VendorOrder.Status.CANCELLED, VendorOrder.Status.DELIVERED]
            )
            for vendor_order in active_orders.only("id", "items_snapshot"):
                if any(
                    str(item.get("vendor_product_id")) == str(listing.pk)
                    for item in (vendor_order.items_snapshot or [])
                    if isinstance(item, dict)
                ):
                    return _error(
                        "این محصول در یک سفارش در حال انجام است؛ تا پایان یا لغو رسمی سفارش امکان حذف از فروش وجود ندارد.",
                        409,
                    )
            # Preserve the catalog/listing record for historical order integrity.
            listing.status = VendorProduct.Status.PAUSED
            listing.stock_quantity = 0
            listing.save(update_fields=("status", "stock_quantity", "updated_at"))
        return JsonResponse({
            "ok": True,
            "listing_id": listing.pk,
            "status": listing.status,
            "message": "محصول از فروش خارج شد؛ سوابق سفارش و حسابداری حفظ شده‌اند.",
        })
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ValidationError as exc:
        return _error(exc)


@login_required
@require_POST
def vendor_wholesale_tier_api(request, listing_id):
    try:
        vendor = _vendor_for_user(request.user)
        payload = _json_body(request)
        if set(payload) - {"minimum_quantity", "unit_price"}:
            return _error("فقط حداقل تعداد و قیمت واحد قابل ثبت است.")
        if vendor.seller_type == Vendor.SellerType.RETAIL:
            return _error("فروش عمده برای این فروشگاه در درخواست فروشندگی تأیید نشده است.", 403)
        with transaction.atomic():
            listing = get_object_or_404(
                VendorProduct.objects.select_for_update(),
                pk=listing_id,
                vendor=vendor,
            )
            if listing.status not in {VendorProduct.Status.ACTIVE, VendorProduct.Status.PENDING, VendorProduct.Status.DRAFT}:
                return _error("وضعیت فعلی محصول اجازه تغییر قیمت عمده را نمی‌دهد.", 409)
            minimum_quantity = _strict_int(payload.get("minimum_quantity", 0), "حداقل تعداد عمده")
            if minimum_quantity not in SELLABLE_UNIT_COUNTS:
                return _error("حداقل تعداد عمده را از فهرست انتخاب کن.")
            tier = WholesalePriceTier(
                listing=listing,
                minimum_quantity=minimum_quantity,
                unit_price=_strict_int(payload.get("unit_price", 0), "قیمت واحد عمده"),
            )
            tier.full_clean()
            tier.save()
            listing.wholesale_enabled = True
            if listing.sale_type == VendorProduct.SaleType.RETAIL:
                listing.sale_type = VendorProduct.SaleType.BOTH
            if listing.status == VendorProduct.Status.ACTIVE:
                listing.status = VendorProduct.Status.PENDING
            listing.save(update_fields=("wholesale_enabled", "sale_type", "status", "updated_at"))
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
        if vendor.seller_type == Vendor.SellerType.RETAIL:
            return _error("فروش عمده برای این فروشگاه تأیید نشده است.", 403)
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
                    listing.sale_type = VendorProduct.SaleType.RETAIL
                listing.status = VendorProduct.Status.PENDING
                listing.save(update_fields=("wholesale_enabled", "sale_type", "status", "updated_at"))
                return JsonResponse({"ok": True, "message": "پله عمده حذف شد و تغییرات برای بررسی ارسال شد."})
            payload = _json_body(request)
            if set(payload) - {"minimum_quantity", "unit_price"} or not payload:
                return _error("فقط حداقل تعداد و قیمت واحد قابل ویرایش است.")
            if "minimum_quantity" in payload:
                minimum_quantity = _strict_int(payload["minimum_quantity"], "حداقل تعداد عمده")
                if minimum_quantity not in SELLABLE_UNIT_COUNTS:
                    return _error("حداقل تعداد عمده را از فهرست انتخاب کن.")
                tier.minimum_quantity = minimum_quantity
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
        if vendor.seller_type == Vendor.SellerType.RETAIL:
            return _error("فروش عمده برای این فروشگاه تأیید نشده است.", 403)
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
                listing.sale_type = VendorProduct.SaleType.RETAIL
            listing.status = VendorProduct.Status.PENDING
            listing.save(update_fields=("wholesale_enabled", "sale_type", "status", "updated_at"))
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
def journal_entries_api(request):
    """Return recent immutable accounting entries for the staff operations screen."""
    try:
        limit = int(request.GET.get("limit", "30"))
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(limit, 100))
    entries = (
        JournalEntry.objects.filter(status__in=[JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED])
        .select_related("order", "vendor_order", "vendor_order__vendor", "created_by")
        .prefetch_related("lines__account")
        .order_by("-posted_at", "-created_at")[:limit]
    )
    results = []
    for entry in entries:
        lines = list(entry.lines.all())
        results.append({
            "id": entry.id,
            "uuid": str(entry.uuid),
            "kind": entry.kind,
            "description": entry.description,
            "status": entry.status,
            "status_label": entry.get_status_display(),
            "posted_at": entry.posted_at.isoformat() if entry.posted_at else entry.created_at.isoformat(),
            "order_reference": entry.order.number if entry.order_id else "",
            "vendor": entry.vendor_order.vendor.store_name if entry.vendor_order_id else "",
            "debit_total": sum(int(line.debit) for line in lines),
            "credit_total": sum(int(line.credit) for line in lines),
            "lines": [{
                "account_code": line.account.code,
                "account_name": line.account.name,
                "debit": int(line.debit),
                "credit": int(line.credit),
                "memo": line.memo,
            } for line in lines],
        })
    return JsonResponse({"ok": True, "results": results})


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
@require_http_methods(["GET", "POST"])
def external_reconciliation_api(request):
    if request.method == "GET":
        records = FinancialReconciliation.objects.select_related("recorded_by").order_by("-created_at")[:100]
        return JsonResponse({"ok": True, "results": [{
            "uuid": str(record.uuid),
            "source": record.source,
            "source_label": record.get_source_display(),
            "external_reference": record.external_reference,
            "internal_reference": record.internal_reference,
            "expected_amount": record.expected_amount,
            "actual_amount": record.actual_amount,
            "currency": record.currency,
            "status": record.status,
            "status_label": record.get_status_display(),
            "delta": None if record.expected_amount is None or record.actual_amount is None else record.actual_amount - record.expected_amount,
            "created_at": record.created_at.isoformat(),
        } for record in records]})
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
    batches = SettlementBatch.objects.select_related("vendor", "approved_by").exclude(
        status__in=[SettlementBatch.Status.DRAFT, SettlementBatch.Status.CANCELLED]
    ).order_by("-created_at")[:100]
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
        "status_label": batch.get_status_display(),
        "payout_reference": batch.payout_reference,
        "failure_reason": batch.failure_reason,
        "paid_at": batch.paid_at.isoformat() if batch.paid_at else None,
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
