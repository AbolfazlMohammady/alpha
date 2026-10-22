import logging
import secrets
from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Address, City, OTP, Province
from apps.orders.services import merge_guest_cart

User = get_user_model()
AUTH_BACKEND = "apps.users.backends.BabaeiAxesBackend"
MIN_PROFILE_AGE = 13

ADDRESS_PROVINCES_CACHE_KEY = "babaei:users:provinces:v1"
ADDRESS_CITIES_CACHE_KEY = "babaei:users:cities:v1"
ADDRESS_GEO_CACHE_TTL = 1800
AUTH_USER_SESSION_KEY = "_auth_user_id"
logger = logging.getLogger(__name__)


def _is_authenticated_session(request):
    return bool(request.session.get(AUTH_USER_SESSION_KEY))


def login_view(request):
    next_url = request.GET.get("next") or request.POST.get("next") or request.session.get("login_next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        request.session["login_next"] = next_url
    else:
        next_url = ""
        request.session.pop("login_next", None)

    if _is_authenticated_session(request):
        return redirect(next_url or "users:profile")
    if request.method == "POST":
        phone = request.POST.get("phone", "").strip()
        if not phone:
            messages.error(request, "شماره موبایل را وارد کنید.")
            return render(request, "users/auth/login.html", {"phone": phone})

        try:
            phone = str(User.objects.normalize_phone(phone))
        except ValueError:
            messages.error(request, "شماره موبایل معتبر نیست.")
            return render(request, "users/auth/login.html", {"phone": phone})

        # Keep only the latest challenge for this phone and remove expired
        # challenges opportunistically so abandoned login attempts do not pile up.
        OTP.objects.filter(phone=phone).delete()
        OTP.objects.filter(expire_at__lte=timezone.now()).delete()

        code = f"{secrets.randbelow(1_000_000):06d}"
        otp = OTP(phone=phone, code=make_password(code))
        otp.save()

        # Development-only fallback while the SMS provider is not configured.
        # Never print OTP values when DEBUG is disabled.
        if settings.DEBUG:
            logger.info("Development OTP for %s: %s", phone, code)

        request.session["otp_phone"] = phone
        request.session["otp_id"] = otp.id
        return redirect("users:verify_otp")
    return render(request, "users/auth/login.html")


def verify_otp_view(request):
    if _is_authenticated_session(request):
        return redirect("users:profile")
    phone = request.session.get("otp_phone")
    otp_id = request.session.get("otp_id")
    if not phone or not otp_id:
        return redirect("users:login")
    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        with transaction.atomic():
            otp = OTP.objects.select_for_update().filter(id=otp_id, phone=phone).first()
            if not otp:
                request.session.pop("otp_phone", None)
                request.session.pop("otp_id", None)
                messages.error(request, "کد تأیید معتبر نیست.")
                return redirect("users:login")

            if not otp.is_valid():
                otp.delete()
                request.session.pop("otp_phone", None)
                request.session.pop("otp_id", None)
                messages.error(request, "کد تأیید منقضی شده است.")
                return redirect("users:login")

            valid_code = check_password(code, otp.code)
            # Backward compatibility for old plaintext OTP rows.
            if not valid_code and len(otp.code) == 6:
                valid_code = secrets.compare_digest(otp.code, code)

            if not valid_code:
                otp.attempts += 1
                if otp.attempts >= 5:
                    otp.delete()
                    request.session.pop("otp_phone", None)
                    request.session.pop("otp_id", None)
                    messages.error(request, "تعداد تلاش‌های مجاز تمام شد؛ کد جدید دریافت کنید.")
                    return redirect("users:login")
                otp.save(update_fields=["attempts"])
                messages.error(request, "کد تأیید صحیح نیست.")
                return render(request, "users/auth/verify_otp.html", {"phone": phone})

            # A successful verification permanently consumes the challenge.
            otp.delete()

        user, _ = User.objects.get_or_create(phone=phone, defaults={"role": "customer"})
        if not user.is_active:
            request.session.pop("otp_phone", None)
            request.session.pop("otp_id", None)
            messages.error(request, "حساب کاربری شما غیرفعال است.")
            return redirect("users:login")

        login(request, user, backend=AUTH_BACKEND)
        merge_guest_cart(request, user)
        next_url = request.session.pop("login_next", "")
        request.session.pop("otp_phone", None)
        request.session.pop("otp_id", None)
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect("users:profile")

    return render(request, "users/auth/verify_otp.html", {"phone": phone})


@login_required
def profile_view(request):
    return render(request, "users/account/profile.html", {"user": request.user})


@login_required
@require_http_methods(["GET", "POST"])
def profile_update_view(request):
    if request.method == "POST":
        user = request.user
        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()
        user.email = request.POST.get("email", "").strip() or None
        user.gender = request.POST.get("gender") or None
        birth_date = request.POST.get("birth_date", "").strip()
        if birth_date:
            try:
                parsed_birth_date = date.fromisoformat(birth_date)
            except ValueError:
                messages.error(request, "تاریخ تولد نامعتبر است.")
                return render(request, "users/account/profile.html", {"user": user})
            today = timezone.localdate()
            minimum_birth_date = date(today.year - MIN_PROFILE_AGE, today.month, today.day)
            if parsed_birth_date >= today:
                messages.error(request, "تاریخ تولد باید قبل از امروز باشد.")
                return render(request, "users/account/profile.html", {"user": user})
            if parsed_birth_date > minimum_birth_date:
                messages.error(request, f"برای ثبت تاریخ تولد، حداقل سن باید {MIN_PROFILE_AGE} سال باشد.")
                return render(request, "users/account/profile.html", {"user": user})
            user.birth_date = parsed_birth_date
        else:
            user.birth_date = None
        if "image" in request.FILES:
            user.image = request.FILES["image"]
        user.save()
        messages.success(request, "اطلاعات حساب با موفقیت ذخیره شد.")
        return redirect("users:profile")
    return render(request, "users/account/profile.html", {"user": request.user})


@login_required
def addresses_view(request):
    addresses = request.user.addresses.select_related("city", "city__province")
    return render(request, "users/account/addresses.html", {"addresses": addresses})


def _address_context(address=None, selected_province_id=None):
    provinces = cache.get(ADDRESS_PROVINCES_CACHE_KEY)
    if provinces is None:
        provinces = list(Province.objects.only("id", "name").order_by("name"))
        cache.set(ADDRESS_PROVINCES_CACHE_KEY, provinces, ADDRESS_GEO_CACHE_TTL)
    cities = cache.get(ADDRESS_CITIES_CACHE_KEY)
    if cities is None:
        cities = list(City.objects.select_related("province").only("id", "name", "province_id", "province__id", "province__name").order_by("province__name", "name"))
        cache.set(ADDRESS_CITIES_CACHE_KEY, cities, ADDRESS_GEO_CACHE_TTL)
    if selected_province_id is None and address and address.city_id:
        selected_province_id = address.city.province_id
    return {"address": address, "provinces": provinces, "cities": cities, "selected_province_id": int(selected_province_id) if selected_province_id else None}


def _validate_city_province(city_id, province_id):
    if not province_id or not city_id:
        raise ValidationError("استان و شهر را انتخاب کنید.")
    city = City.objects.select_related("province").filter(pk=city_id, province_id=province_id).first()
    if not city:
        raise ValidationError("شهر انتخاب‌شده متعلق به استان انتخاب‌شده نیست.")
    return city


@login_required
@require_http_methods(["GET", "POST"])
def address_create_view(request):
    if request.method == "POST":
        address = Address(
            user=request.user,
            title=request.POST.get("title", "").strip(),
            phone=request.POST.get("phone", "").strip(),
            is_for_other=request.POST.get("is_for_other") == "1",
            recipient_name=request.POST.get("recipient_name", "").strip(),
            description=request.POST.get("description", "").strip(),
            postal_code=request.POST.get("postal_code", "").strip(),
        )
        province_id = request.POST.get("province")
        try:
            address.city = _validate_city_province(request.POST.get("city"), province_id)
            address.full_clean()
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if exc.messages else "اطلاعات آدرس صحیح نیست.")
            return render(request, "users/account/address_form.html", _address_context(address, province_id))
        address.save()
        messages.success(request, "آدرس با موفقیت اضافه شد.")
        return redirect("users:addresses")
    return render(request, "users/account/address_form.html", _address_context())


@login_required
@require_http_methods(["GET", "POST"])
def address_update_view(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    if request.method == "POST":
        address.title = request.POST.get("title", "").strip()
        address.phone = request.POST.get("phone", "").strip()
        address.is_for_other = request.POST.get("is_for_other") == "1"
        address.recipient_name = request.POST.get("recipient_name", "").strip()
        address.description = request.POST.get("description", "").strip()
        address.postal_code = request.POST.get("postal_code", "").strip()
        province_id = request.POST.get("province")
        try:
            address.city = _validate_city_province(request.POST.get("city"), province_id)
            address.full_clean()
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if exc.messages else "اطلاعات آدرس صحیح نیست.")
            return render(request, "users/account/address_form.html", _address_context(address, province_id))
        address.save()
        messages.success(request, "آدرس با موفقیت ویرایش شد.")
        return redirect("users:addresses")
    return render(request, "users/account/address_form.html", _address_context(address))


@login_required
@require_http_methods(["POST"])
def address_delete_view(request, pk):
    address = get_object_or_404(Address, pk=pk, user=request.user)
    address.delete()
    messages.success(request, "آدرس حذف شد.")
    return redirect("users:addresses")


@login_required
@require_http_methods(["POST"])
def logout_view(request):
    logout(request)
    return redirect("users:login")
