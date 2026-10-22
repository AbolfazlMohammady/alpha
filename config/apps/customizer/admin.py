from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Artwork,
    ArtworkAreaPrice,
    CustomizerPricingSettings,
    DesignDraft,
    DesignLayer,
    DesignerView,
    PrintArea,
    PrintAreaView,
    Product3DAsset,
    Product3DSource,
)


class CustomizerAdminMixin:
    show_full_result_count = False
    list_per_page = 30


class PrintAreaViewInline(admin.TabularInline):
    model = PrintAreaView
    extra = 0
    fields = ("view", "geometry")
    autocomplete_fields = ("view",)


class ArtworkAreaPriceInline(admin.TabularInline):
    model = ArtworkAreaPrice
    extra = 0
    autocomplete_fields = ("area",)
    fields = ("area", "price")


class DesignLayerInline(admin.TabularInline):
    model = DesignLayer
    extra = 0
    readonly_fields = ("artwork", "area", "x", "y", "width", "height", "rotation", "z_index")
    fields = readonly_fields
    can_delete = False


@admin.action(description="فعال‌سازی طرح‌های انتخاب‌شده")
def activate_artworks(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="غیرفعال‌سازی طرح‌های انتخاب‌شده")
def deactivate_artworks(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.register(CustomizerPricingSettings)
class CustomizerPricingSettingsAdmin(CustomizerAdminMixin, admin.ModelAdmin):
    fieldsets = (
        ("قیمت‌گذاری استودیو", {"fields": ("tshirt_base_price", "customer_label_price")}),
        ("سیستم", {"fields": ("updated_at",), "classes": ("collapse",)}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not CustomizerPricingSettings.objects.exists()



@admin.register(Artwork)
class ArtworkAdmin(CustomizerAdminMixin, admin.ModelAdmin):
    list_display = ("preview", "name", "code", "source_badge", "processing_badge", "price_display", "status_badge", "created_at")
    list_filter = ("source", "processing_status", "background_removed", "is_active", "created_at")
    search_fields = ("name", "slug", "code", "owner__phone")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("owner",)
    inlines = (ArtworkAreaPriceInline,)
    readonly_fields = ("uuid", "code", "created_at", "updated_at", "preview_large")
    date_hierarchy = "created_at"
    actions = (activate_artworks, deactivate_artworks)
    fieldsets = (
        ("لیبل", {"fields": ("preview_large", "name", "code", "slug", "image", "original_image"), "classes": ("ba-admin-section", "ba-admin-section--media")}),
        ("پردازش", {"fields": ("source", "processing_status", "background_removed", "min_width_px"), "classes": ("ba-admin-section", "ba-admin-section--processing")}),
        ("قیمت و مالکیت", {"fields": ("base_price", "owner", "session_key"), "classes": ("ba-admin-section", "ba-admin-section--commercial")}),
        ("انتشار", {"fields": ("is_active",), "classes": ("ba-admin-section", "ba-admin-section--publish")}),
        ("سیستم", {"fields": ("uuid", "created_at", "updated_at"), "classes": ("collapse", "ba-admin-section", "ba-admin-section--system")}),
    )

    @admin.display(description="تصویر")
    def preview(self, obj):
        if not obj.image:
            return "—"
        return format_html('<img class="ba-thumb ba-thumb--artwork" src="{}" alt="">', obj.image.url)

    @admin.display(description="پیش‌نمایش")
    def preview_large(self, obj):
        if not obj.image:
            return "تصویری ثبت نشده"
        return format_html('<img class="ba-artwork-preview" src="{}" alt="">', obj.image.url)

    @admin.display(description="منبع")
    def source_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-gold" if obj.source == Artwork.Source.LIBRARY else "is-blue", obj.get_source_display())

    @admin.display(description="پردازش")
    def processing_badge(self, obj):
        css = {"ready":"is-on","processing":"is-warning","failed":"is-danger"}.get(obj.processing_status, "is-off")
        return format_html('<span class="ba-status {}">{}</span>', css, obj.get_processing_status_display())

    @admin.display(description="قیمت")
    def price_display(self, obj):
        return format_html("{} <small>تومان</small>", f"{obj.base_price:,}")

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-on" if obj.is_active else "is-off", "فعال" if obj.is_active else "غیرفعال")


@admin.register(DesignerView)
class DesignerViewAdmin(CustomizerAdminMixin, admin.ModelAdmin):
    list_display = ("preview", "product", "name", "key", "has_3d_model", "angle", "sort_order", "status_badge")
    list_filter = ("is_active", "product", "sort_order")
    search_fields = ("product__name", "name", "key")
    autocomplete_fields = ("product",)
    readonly_fields = ("preview_large",)
    fieldsets = (
        ("نما", {"fields": ("product", "key", "name", "is_active", "sort_order", "angle")}),
        ("تصاویر", {"fields": ("preview_large", "background_image", "mask_image", "canvas_width", "canvas_height")}),
        ("مدل سه‌بعدی", {"fields": ("model_3d", "model_3d_url", "model_3d_scale")}),
    )

    @admin.display(description="پیش‌نمایش")
    def preview(self, obj):
        if not obj.background_image:
            return "—"
        return format_html('<img class="ba-thumb" src="{}" alt="">', obj.background_image.url)

    @admin.display(description="تصویر")
    def preview_large(self, obj):
        if not obj.background_image:
            return "تصویری ثبت نشده"
        return format_html('<img class="ba-artwork-preview ba-artwork-preview--model" src="{}" alt="">', obj.background_image.url)

    @admin.display(boolean=True, description="مدل ۳D")
    def has_3d_model(self, obj):
        return bool(obj.model_3d or obj.model_3d_url)

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-on" if obj.is_active else "is-off", "فعال" if obj.is_active else "غیرفعال")


@admin.register(PrintArea)
class PrintAreaAdmin(CustomizerAdminMixin, admin.ModelAdmin):
    list_display = ("product", "name", "key", "side", "max_width_mm", "max_height_mm", "max_layers", "status_badge")
    list_filter = ("is_active", "product")
    search_fields = ("product__name", "name", "key")
    autocomplete_fields = ("product",)
    inlines = (PrintAreaViewInline,)
    fieldsets = (
        ("ناحیه چاپ", {"fields": ("product", "key", "name", "side", "is_active", "sort_order")}),
        ("محدودیت چاپ", {"fields": ("max_width_mm", "max_height_mm", "max_layers")}),
    )

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        return format_html('<span class="ba-status {}">{}</span>', "is-on" if obj.is_active else "is-off", "فعال" if obj.is_active else "غیرفعال")


@admin.register(Product3DAsset)
class Product3DAssetAdmin(CustomizerAdminMixin, admin.ModelAdmin):
    list_display = ("product", "status_badge", "provider", "progress_bar", "task_id", "updated_at")
    list_filter = ("status", "provider", "updated_at")
    search_fields = ("product__name", "task_id", "error_message")
    autocomplete_fields = ("product",)
    readonly_fields = ("status", "task_id", "progress", "analysis", "source_signature", "error_message", "created_at", "updated_at")
    fieldsets = (
        ("پردازش", {"fields": ("product", "provider", "status", "progress", "task_id", "error_message")}),
        ("مدل نهایی", {"fields": ("model_3d", "model_url", "preview_image")}),
        ("تحلیل تصاویر", {"fields": ("analysis", "source_signature")}),
        ("زمان‌ها", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        css = {"pending":"is-warning","processing":"is-blue","ready":"is-on","failed":"is-danger"}.get(obj.status, "is-off")
        return format_html('<span class="ba-status {}">{}</span>', css, obj.get_status_display())

    @admin.display(description="پیشرفت")
    def progress_bar(self, obj):
        value = max(0, min(100, int(obj.progress or 0)))
        return format_html('<span class="ba-progress"><i style="width:{}%"></i><b>{}%</b></span>', value, value)


@admin.register(Product3DSource)
class Product3DSourceAdmin(CustomizerAdminMixin, admin.ModelAdmin):
    list_display = ("asset", "product_image", "background_removed", "sort_order", "created_at")
    list_filter = ("background_removed", "created_at")
    search_fields = ("asset__product__name", "product_image__product__name")
    autocomplete_fields = ("asset", "product_image")
    readonly_fields = ("created_at",)
    ordering = ("asset", "sort_order")


@admin.register(DesignDraft)
class DesignDraftAdmin(CustomizerAdminMixin, admin.ModelAdmin):
    list_display = ("preview", "design_code", "product", "variant", "status_badge", "base_price_display", "total_price_display", "updated_at")
    list_filter = ("status", "product", "updated_at")
    search_fields = ("uuid", "design_code", "product__name", "user__phone", "session_key")
    autocomplete_fields = ("product", "variant", "user")
    readonly_fields = ("uuid", "design_code", "payload", "total_price", "created_at", "updated_at", "preview_front_large", "preview_back_large")
    inlines = (DesignLayerInline,)
    date_hierarchy = "updated_at"
    fieldsets = (
        ("طرح", {"fields": ("preview_large", "preview_front_large", "preview_back_large", "uuid", "design_code", "product", "variant", "user", "session_key", "status", "shirt_color")}),
        ("مبلغ", {"fields": ("base_price", "total_price")}),
        ("داده طرح", {"fields": ("payload",), "classes": ("collapse",)}),
        ("زمان‌ها", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="پیش‌نمایش")
    def preview(self, obj):
        if not obj.preview_front:
            return format_html('<span class="ba-thumb ba-thumb--empty">—</span>')
        return format_html('<img class="ba-thumb ba-thumb--artwork" src="{}" alt="">', obj.preview_front.url)

    @admin.display(description="کد طراحی")
    def design_code(self, obj):
        return obj.design_code

    @admin.display(description="قیمت پایه")
    def base_price_display(self, obj):
        return format_html('{} <small>تومان</small>', f'{obj.base_price:,}')

    @admin.display(description="پیش‌نمایش جلو")
    def preview_front_large(self, obj):
        if not obj.preview_front:
            return "ثبت نشده"
        return format_html('<img class="ba-artwork-preview" src="{}" alt="">', obj.preview_front.url)

    @admin.display(description="پیش‌نمایش پشت")
    def preview_back_large(self, obj):
        if not obj.preview_back:
            return "ثبت نشده"
        return format_html('<img class="ba-artwork-preview" src="{}" alt="">', obj.preview_back.url)

    @admin.display(description="شناسه")
    def uuid_short(self, obj):
        return str(obj.uuid)[:8]

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        css = {"draft":"is-warning","confirmed":"is-on","expired":"is-danger"}.get(obj.status, "is-off")
        return format_html('<span class="ba-status {}">{}</span>', css, obj.get_status_display())

    @admin.display(description="مبلغ")
    def total_price_display(self, obj):
        return format_html('{} <small>تومان</small>', f'{obj.total_price:,}')


@admin.register(ArtworkAreaPrice)
class ArtworkAreaPriceAdmin(CustomizerAdminMixin, admin.ModelAdmin):
    list_display = ("artwork", "area", "product_display", "price_display")
    search_fields = ("artwork__name", "area__name", "area__product__name")
    list_filter = ("area__product",)
    autocomplete_fields = ("artwork", "area")

    @admin.display(description="محصول")
    def product_display(self, obj):
        return obj.area.product.name

    @admin.display(description="قیمت")
    def price_display(self, obj):
        return format_html("{} <small>تومان</small>", f"{obj.price:,}")


@admin.register(DesignLayer)
class DesignLayerAdmin(CustomizerAdminMixin, admin.ModelAdmin):
    list_display = ("draft", "layer_type", "artwork", "side", "area", "position_display", "size_display", "rotation", "z_index")
    search_fields = ("draft__uuid", "artwork__name", "area__name")
    autocomplete_fields = ("draft", "artwork", "area")
    readonly_fields = ("draft", "artwork", "area", "x", "y", "width", "height", "rotation", "z_index")

    @admin.display(description="موقعیت")
    def position_display(self, obj):
        return f"{obj.x:.2f} / {obj.y:.2f}"

    @admin.display(description="اندازه")
    def size_display(self, obj):
        return f"{obj.width:.2f} × {obj.height:.2f}"
