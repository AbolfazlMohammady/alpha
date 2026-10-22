from django.contrib import admin
from django.db.models import Count, Min, Prefetch, Sum
from django.utils.html import format_html

from .models import Category, Product, ProductColor, ProductComment, ProductImage, ProductSize, ProductVariant


class ShopAdminMixin:
    show_full_result_count = False
    list_per_page = 30


@admin.register(Category)
class CategoryAdmin(ShopAdminMixin, admin.ModelAdmin):
    list_display = ("admin_preview", "name", "product_count", "status_badge", "sort_order", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("sort_order", "name")
    readonly_fields = ("uuid", "created_at", "updated_at")
    date_hierarchy = "created_at"
    fieldsets = (
        ("اطلاعات دسته‌بندی", {"fields": ("name", "slug", "description", "image")}),
        ("نمایش", {"fields": ("is_active", "sort_order")}),
        ("سئو", {"fields": ("seo_title", "seo_description"), "classes": ("collapse",)}),
        ("سیستم", {"fields": ("uuid", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_product_count=Count("products", distinct=True))

    @admin.display(description="پیش‌نمایش")
    def admin_preview(self, obj):
        if not obj.image:
            return format_html('<span class="ba-thumb ba-thumb--empty">—</span>')
        return format_html('<img class="ba-thumb" src="{}" alt="">', obj.image.url)

    @admin.display(description="محصولات", ordering="_product_count")
    def product_count(self, obj):
        return obj._product_count

    @admin.display(description="وضعیت", boolean=False)
    def status_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-on" if obj.is_active else "is-off", "فعال" if obj.is_active else "غیرفعال")


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    fields = ("image_preview", "image", "alt_text", "image_type", "sort_order")
    readonly_fields = ("image_preview",)
    ordering = ("sort_order", "id")

    @admin.display(description="پیش‌نمایش")
    def image_preview(self, obj):
        if not obj.image:
            return "—"
        return format_html('<img class="ba-inline-thumb" src="{}" alt="">', obj.image.url)


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = ("color", "size", "sku", "price", "compare_at_price", "stock_quantity", "is_active")
    autocomplete_fields = ("color", "size")
    ordering = ("color", "size")


@admin.action(description="فعال‌سازی محصولات انتخاب‌شده")
def activate_products(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="غیرفعال‌سازی محصولات انتخاب‌شده")
def deactivate_products(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.action(description="ویژه‌کردن محصولات انتخاب‌شده")
def feature_products(modeladmin, request, queryset):
    queryset.update(is_featured=True)


@admin.action(description="برداشتن ویژه‌بودن محصولات")
def unfeature_products(modeladmin, request, queryset):
    queryset.update(is_featured=False)


@admin.register(Product)
class ProductAdmin(ShopAdminMixin, admin.ModelAdmin):
    list_display = ("admin_preview", "name", "category", "price_display", "stock_display", "featured_badge", "status_badge", "created_at")
    list_filter = ("is_active", "is_featured", "category", "created_at")
    search_fields = ("name", "slug", "short_description", "description", "variants__sku")
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ("category",)
    autocomplete_fields = ("category",)
    inlines = (ProductImageInline, ProductVariantInline)
    readonly_fields = ("uuid", "created_at", "updated_at", "public_link")
    date_hierarchy = "created_at"
    actions = (activate_products, deactivate_products, feature_products, unfeature_products)
    fieldsets = (
        ("محصول", {"fields": ("name", "category", "slug", "short_description", "description")}),
        ("قیمت‌گذاری", {"fields": ("base_price", "compare_at_price")}),
        ("انتشار", {"fields": ("is_active", "is_featured")}),
        ("سئو", {"fields": ("seo_title", "seo_description"), "classes": ("collapse",)}),
        ("سیستم", {"fields": ("public_link", "uuid", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        primary_images = ProductImage.objects.filter(
            image_type=ProductImage.ImageType.PRIMARY
        ).only("id", "product_id", "image").order_by("id")
        return (
            super().get_queryset(request)
            .annotate(
                _stock=Sum("variants__stock_quantity"),
                _min_price=Min("variants__price"),
            )
            .prefetch_related(
                Prefetch("images", queryset=primary_images, to_attr="_admin_primary_images")
            )
        )

    @admin.display(description="پیش‌نمایش")
    def admin_preview(self, obj):
        images = getattr(obj, "_admin_primary_images", [])
        image = images[0] if images else None
        if not image:
            image = obj.images.first()
        if not image:
            return format_html('<span class="ba-thumb ba-thumb--empty">—</span>')
        return format_html('<img class="ba-thumb" src="{}" alt="">', image.image.url)

    @admin.display(description="قیمت", ordering="_min_price")
    def price_display(self, obj):
        price = obj._min_price or obj.base_price
        return format_html('<strong class="ba-price">{}</strong> <small>تومان</small>', f"{price:,}")

    @admin.display(description="موجودی", ordering="_stock")
    def stock_display(self, obj):
        stock = obj._stock or 0
        css = "is-danger" if stock == 0 else "is-warning" if stock < 5 else "is-on"
        return format_html('<span class="ba-stock {}">{}</span>', css, stock)

    @admin.display(description="ویژه")
    def featured_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-gold" if obj.is_featured else "is-off", "ویژه" if obj.is_featured else "—")

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-on" if obj.is_active else "is-off", "فعال" if obj.is_active else "غیرفعال")

    @admin.display(description="لینک محصول")
    def public_link(self, obj):
        if not obj.pk:
            return "پس از ذخیره در دسترس است."
        return format_html('<a href="{}" target="_blank" rel="noopener">مشاهده محصول ↗</a>', obj.get_absolute_url())


@admin.register(ProductColor)
class ProductColorAdmin(ShopAdminMixin, admin.ModelAdmin):
    list_display = ("swatch", "name", "hex_code", "status_badge")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "hex_code")
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (("رنگ", {"fields": ("name", "slug", "hex_code", "is_active")}),)

    @admin.display(description="رنگ")
    def swatch(self, obj):
        return format_html('<span class="ba-color-swatch" style="background:{}"></span>', obj.hex_code)

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-on" if obj.is_active else "is-off", "فعال" if obj.is_active else "غیرفعال")


@admin.register(ProductSize)
class ProductSizeAdmin(ShopAdminMixin, admin.ModelAdmin):
    list_display = ("name", "sort_order", "status_badge")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("sort_order", "name")
    fieldsets = (("سایز", {"fields": ("name", "slug", "sort_order", "is_active")}),)

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-on" if obj.is_active else "is-off", "فعال" if obj.is_active else "غیرفعال")


@admin.register(ProductVariant)
class ProductVariantAdmin(ShopAdminMixin, admin.ModelAdmin):
    list_display = ("product", "color_badge", "size", "sku", "price_display", "stock_badge", "status_badge")
    list_filter = ("is_active", "color", "size", "product__category")
    search_fields = ("product__name", "sku", "color__name", "size__name")
    list_select_related = ("product", "color", "size")
    autocomplete_fields = ("product", "color", "size")
    ordering = ("product", "color", "size")

    @admin.display(description="رنگ")
    def color_badge(self, obj):
        return format_html('<span class="ba-color-inline"><i style="background:{}"></i>{}</span>', obj.color.hex_code, obj.color.name)

    @admin.display(description="قیمت")
    def price_display(self, obj):
        return format_html('{} <small>تومان</small>', f"{obj.price:,}")

    @admin.display(description="موجودی")
    def stock_badge(self, obj):
        css = "is-danger" if obj.stock_quantity == 0 else "is-warning" if obj.stock_quantity < 5 else "is-on"
        return format_html('<span class="ba-stock {}">{}</span>', css, obj.stock_quantity)

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-on" if obj.is_active else "is-off", "فعال" if obj.is_active else "غیرفعال")


@admin.register(ProductImage)
class ProductImageAdmin(ShopAdminMixin, admin.ModelAdmin):
    list_display = ("preview", "product", "image_type", "sort_order", "alt_text")
    list_filter = ("image_type", "product__category")
    search_fields = ("product__name", "alt_text")
    list_select_related = ("product",)
    autocomplete_fields = ("product",)
    ordering = ("product", "sort_order", "id")

    @admin.display(description="تصویر")
    def preview(self, obj):
        if not obj.image:
            return "—"
        return format_html('<img class="ba-thumb" src="{}" alt="">', obj.image.url)


@admin.action(description="تأیید نظرات انتخاب‌شده")
def approve_comments(modeladmin, request, queryset):
    queryset.update(status=ProductComment.Status.APPROVED)


@admin.action(description="رد نظرات انتخاب‌شده")
def reject_comments(modeladmin, request, queryset):
    queryset.update(status=ProductComment.Status.REJECTED)


@admin.register(ProductComment)
class ProductCommentAdmin(ShopAdminMixin, admin.ModelAdmin):
    list_display = ("product", "user_display", "rating_display", "verified_badge", "status_badge", "created_at")
    list_filter = ("status", "verified_purchase", "rating", "created_at")
    search_fields = ("product__name", "user__phone", "user__first_name", "user__last_name", "body")
    list_select_related = ("product", "user")
    autocomplete_fields = ("product", "user")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = (approve_comments, reject_comments)
    fieldsets = (
        ("نظر", {"fields": ("product", "user", "body", "rating")}),
        ("بررسی", {"fields": ("status", "verified_purchase")}),
        ("سیستم", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="کاربر")
    def user_display(self, obj):
        name = obj.display_name
        return format_html("<strong>{}</strong><small class=\"ba-subline\">{}</small>", name, obj.user.phone)

    @admin.display(description="امتیاز")
    def rating_display(self, obj):
        return "—" if obj.rating is None else f"{obj.rating} / ۵"

    @admin.display(description="خرید")
    def verified_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-on" if obj.verified_purchase else "is-off", "تأییدشده" if obj.verified_purchase else "—")

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        css = {ProductComment.Status.APPROVED: "is-on", ProductComment.Status.PENDING: "is-warning", ProductComment.Status.REJECTED: "is-off"}.get(obj.status, "is-off")
        return format_html('<span class="ba-status {}">{}</span>', css, obj.get_status_display())
