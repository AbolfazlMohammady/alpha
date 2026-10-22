from django.contrib import admin
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from .models import (
    JournalEntry, JournalLine, LedgerAccount, SettlementBatch, SettlementLine,
    Shipment, Vendor, VendorOrder, VendorProduct, WholesalePriceTier,
)


class ReadOnlyAuditAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("store_name", "user", "status_badge", "commission_bps", "supports_custom_printing", "created_at")
    list_filter = ("status", "supports_custom_printing", "created_at")
    search_fields = ("store_name", "slug", "user__phone", "user__email")
    autocomplete_fields = ("user",)
    readonly_fields = ("uuid", "created_at", "updated_at", "approved_at")
    list_select_related = ("user",)
    actions = ("approve_vendors", "suspend_vendors")

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        css = {Vendor.Status.ACTIVE: "success", Vendor.Status.PENDING: "warning", Vendor.Status.SUSPENDED: "danger"}.get(obj.status, "secondary")
        return format_html('<span class="badge badge-{}">{}</span>', css, obj.get_status_display())

    @admin.action(description="تأیید فروشندگان انتخاب‌شده")
    def approve_vendors(self, request, queryset):
        from django.utils import timezone
        updated = queryset.filter(status=Vendor.Status.PENDING).update(status=Vendor.Status.ACTIVE, approved_at=timezone.now())
        self.message_user(request, f"{updated} فروشنده تأیید شد.")

    @admin.action(description="تعلیق فروشندگان انتخاب‌شده")
    def suspend_vendors(self, request, queryset):
        updated = queryset.exclude(status=Vendor.Status.SUSPENDED).update(status=Vendor.Status.SUSPENDED)
        self.message_user(request, f"{updated} فروشنده تعلیق شد.")


class WholesaleTierInline(admin.TabularInline):
    model = WholesalePriceTier
    extra = 0


@admin.register(VendorProduct)
class VendorProductAdmin(admin.ModelAdmin):
    list_display = ("product", "vendor", "status", "retail_price", "stock_quantity", "wholesale_enabled", "supports_custom_printing")
    list_filter = ("status", "wholesale_enabled", "supports_custom_printing", "vendor")
    search_fields = ("product__name", "vendor__store_name", "product__slug")
    autocomplete_fields = ("vendor", "product")
    inlines = (WholesaleTierInline,)
    readonly_fields = ("created_at", "updated_at")


@admin.register(WholesalePriceTier)
class WholesalePriceTierAdmin(admin.ModelAdmin):
    list_display = ("listing", "minimum_quantity", "unit_price", "created_at")
    list_filter = ("created_at",)
    search_fields = ("listing__product__name", "listing__vendor__store_name")
    autocomplete_fields = ("listing",)
    readonly_fields = ("created_at",)


@admin.register(VendorOrder)
class VendorOrderAdmin(ReadOnlyAuditAdmin):
    list_display = ("order", "vendor", "status", "subtotal", "commission_amount", "vendor_payable", "settlement_eligible_at")
    list_filter = ("status", "created_at")
    search_fields = ("order__number", "vendor__store_name")
    list_select_related = ("order", "vendor")
    readonly_fields = tuple(field.name for field in VendorOrder._meta.fields)


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("vendor_order", "provider", "status", "tracking_number", "quoted_cost", "actual_cost", "created_at")
    list_filter = ("provider", "status", "payer", "created_at")
    search_fields = ("tracking_number", "external_shipment_id", "vendor_order__order__number", "vendor_order__vendor__store_name")
    readonly_fields = ("uuid", "created_at", "updated_at", "booked_at", "handed_over_at", "delivered_at", "last_event_at")
    list_select_related = ("vendor_order", "vendor_order__vendor", "vendor_order__order")


@admin.register(LedgerAccount)
class LedgerAccountAdmin(ReadOnlyAuditAdmin):
    list_display = ("code", "name", "kind", "vendor", "currency", "is_active")
    list_filter = ("kind", "currency", "is_active")
    search_fields = ("code", "name", "vendor__store_name")
    list_select_related = ("vendor",)


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0
    can_delete = False
    readonly_fields = ("account", "debit", "credit", "currency", "memo")
    fields = readonly_fields
    show_change_link = False


@admin.register(JournalEntry)
class JournalEntryAdmin(ReadOnlyAuditAdmin):
    list_display = ("id", "kind", "status", "description", "order", "vendor_order", "posted_at")
    list_filter = ("kind", "status", "posted_at")
    search_fields = ("idempotency_key", "description", "order__number")
    list_select_related = ("order", "vendor_order", "created_by")
    inlines = (JournalLineInline,)
    readonly_fields = tuple(field.name for field in JournalEntry._meta.fields)


@admin.register(JournalLine)
class JournalLineAdmin(ReadOnlyAuditAdmin):
    list_display = ("entry", "account", "debit", "credit", "currency", "memo")
    list_filter = ("currency", "account__kind")
    search_fields = ("entry__idempotency_key", "account__code", "memo")
    list_select_related = ("entry", "account")


class SettlementLineInline(admin.TabularInline):
    model = SettlementLine
    extra = 0
    can_delete = False
    readonly_fields = ("vendor_order", "gross_amount", "commission_amount", "payable_amount", "created_at")
    fields = readonly_fields


@admin.register(SettlementBatch)
class SettlementBatchAdmin(ReadOnlyAuditAdmin):
    list_display = ("id", "vendor", "status", "gross_amount", "commission_amount", "payable_amount", "approved_by", "created_at", "paid_at")
    list_filter = ("status", "created_at", "paid_at")
    search_fields = ("vendor__store_name", "idempotency_key", "payout_reference")
    list_select_related = ("vendor", "approved_by")
    inlines = (SettlementLineInline,)
    readonly_fields = tuple(field.name for field in SettlementBatch._meta.fields)


@admin.register(SettlementLine)
class SettlementLineAdmin(ReadOnlyAuditAdmin):
    list_display = ("batch", "vendor_order", "gross_amount", "commission_amount", "payable_amount")
    list_select_related = ("batch", "vendor_order")
