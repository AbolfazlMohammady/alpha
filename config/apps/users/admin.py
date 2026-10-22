from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html

from .models import Address, City, OTP, Province, User


class UsersAdminMixin:
    show_full_result_count = False
    list_per_page = 30


@admin.register(User)
class UserAdmin(UsersAdminMixin, admin.ModelAdmin):
    list_display = ("avatar_preview", "customer_display", "phone_display", "role_badge", "orders_count", "active_badge", "date_joined")
    list_filter = ("role", "is_active", "is_staff", "is_superuser", "gender", "date_joined")
    search_fields = ("phone", "email", "first_name", "last_name")
    readonly_fields = ("uuid", "date_joined", "last_login", "orders_count", "profile_preview")
    ordering = ("-date_joined",)
    date_hierarchy = "date_joined"
    add_fieldsets = (
        ("پروفایل", {"fields": ("image", "first_name", "last_name", "phone", "email", "gender", "birth_date")}),
        ("دسترسی", {"fields": ("role", "is_active")}),
        ("امنیت", {"fields": ("password",)}),
    )
    fieldsets = (
        ("پروفایل", {"fields": ("profile_preview", "image", "first_name", "last_name", "phone", "email", "gender", "birth_date")}),
        ("دسترسی", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("امنیت", {"fields": ("password", "last_login"), "classes": ("collapse",)}),
        ("سیستم", {"fields": ("uuid", "date_joined"), "classes": ("collapse",)}),
    )

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

    def save_model(self, request, obj, form, change):
        import os

        designated_phone = (os.environ.get("SUPERUSER_PHONE") or "").strip()
        try:
            designated_phone = User.objects.normalize_phone(designated_phone) if designated_phone else ""
        except ValueError:
            designated_phone = ""
        is_designated = bool(
            designated_phone
            and str(obj.phone) == str(designated_phone)
        )
        obj.is_staff = is_designated
        obj.is_superuser = is_designated
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_orders_count=Count("orders", distinct=True))

    @admin.display(description="کاربر")
    def avatar_preview(self, obj):
        if obj.image:
            return format_html('<img class="ba-avatar" src="{}" alt="">', obj.image.url)

        fallback_source = str(obj.first_name or obj.phone or "?")
        return format_html(
            '<span class="ba-avatar-fallback">{}</span>',
            fallback_source[0].upper(),
        )

    @admin.display(description="نام")
    def customer_display(self, obj):
        name = f"{obj.first_name} {obj.last_name}".strip() or "بدون نام"
        return format_html('<strong>{}</strong><small class="ba-subline">{}</small>', name, obj.email or "ایمیل ثبت نشده")

    @admin.display(description="شماره")
    def phone_display(self, obj):
        return str(obj.phone)

    @admin.display(description="نقش")
    def role_badge(self, obj):
        return format_html('<span class="ba-status is-gold">{}</span>', obj.get_role_display())

    @admin.display(description="سفارش", ordering="_orders_count")
    def orders_count(self, obj):
        return obj._orders_count

    @admin.display(description="وضعیت")
    def active_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-on" if obj.is_active else "is-danger", "فعال" if obj.is_active else "مسدود")

    @admin.display(description="پروفایل")
    def profile_preview(self, obj):
        return self.avatar_preview(obj)


@admin.register(Address)
class AddressAdmin(UsersAdminMixin, admin.ModelAdmin):
    list_display = ("title", "user_display", "recipient_display", "city_display", "phone", "default_badge")
    list_filter = ("is_default", "city__province")
    search_fields = ("title", "user__phone", "user__first_name", "user__last_name", "postal_code", "description")
    list_select_related = ("user", "city", "city__province")
    fieldsets = (
        ("مخاطب", {"fields": ("user", "title", "phone", "is_for_other", "recipient_name")}),
        ("آدرس", {"fields": ("city", "postal_code", "description", "is_default")}),
    )

    @admin.display(description="کاربر")
    def user_display(self, obj):
        return format_html('<strong>{}</strong><small class="ba-subline">{}</small>', f"{obj.user.first_name} {obj.user.last_name}".strip() or "مشتری", obj.user.phone)

    @admin.display(description="تحویل‌گیرنده")
    def recipient_display(self, obj):
        if obj.is_for_other:
            return format_html('<strong>{}</strong><small class="ba-subline">شخص دیگر</small>', obj.recipient_name or "نام ثبت نشده")
        return format_html('<strong>{}</strong><small class="ba-subline">خود کاربر</small>', obj.user.get_full_name().strip() or "نام پروفایل ثبت نشده")

    @admin.display(description="مکان")
    def city_display(self, obj):
        return f"{obj.city.province.name} / {obj.city.name}"

    @admin.display(description="پیش‌فرض")
    def default_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-gold" if obj.is_default else "is-off", "پیش‌فرض" if obj.is_default else "—")


@admin.register(Province)
class ProvinceAdmin(UsersAdminMixin, admin.ModelAdmin):
    list_display = ("name", "city_count")
    search_fields = ("name",)
    ordering = ("name",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_city_count=Count("cities"))

    @admin.display(description="شهرها", ordering="_city_count")
    def city_count(self, obj):
        return obj._city_count


@admin.register(City)
class CityAdmin(UsersAdminMixin, admin.ModelAdmin):
    list_display = ("name", "province", "address_count")
    list_filter = ("province",)
    search_fields = ("name", "province__name")
    list_select_related = ("province",)
    ordering = ("province__name", "name")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_address_count=Count("addresses"))

    @admin.display(description="آدرس‌ها", ordering="_address_count")
    def address_count(self, obj):
        return obj._address_count


@admin.register(OTP)
class OTPAdmin(UsersAdminMixin, admin.ModelAdmin):
    list_display = ("phone", "created_at", "expire_at", "valid_badge", "used_badge")
    list_filter = ("is_used", "created_at", "expire_at")
    search_fields = ("phone",)
    readonly_fields = ("created_at", "expire_at", "is_valid_readonly")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    @admin.display(description="اعتبار")
    def valid_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-on" if obj.is_valid() else "is-danger", "معتبر" if obj.is_valid() else "منقضی")

    @admin.display(description="استفاده")
    def used_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-danger" if obj.is_used else "is-warning", "استفاده شده" if obj.is_used else "استفاده نشده")

    @admin.display(description="وضعیت فعلی")
    def is_valid_readonly(self, obj):
        return self.valid_badge(obj)
