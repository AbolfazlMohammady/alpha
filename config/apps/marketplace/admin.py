from django.contrib import admin
from django.core.exceptions import ValidationError
from django.utils.html import format_html
from django.utils.text import slugify
from django.db import IntegrityError, transaction
from django.contrib.admin import helpers
from django.template.response import TemplateResponse

from apps.shop.models import Category, Product, ProductImage

from .models import (
    CategoryRequest, FinancialReconciliation, VendorApplication, JournalEntry, JournalLine, LedgerAccount, SettlementBatch, SettlementLine,
    Shipment, ShippingQuote, Vendor, VendorOrder, VendorProduct, VendorProductSubmission, WholesalePriceTier,
)


class ReadOnlyAuditAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VendorApplication)
class VendorApplicationAdmin(admin.ModelAdmin):
    list_display = ("store_name", "contact_name", "contact_phone", "seller_type", "status", "created_at", "reviewed_at")
    list_filter = ("status", "seller_type", "created_at")
    search_fields = ("store_name", "contact_name", "contact_phone", "contact_email", "user__phone", "user__email")
    list_select_related = ("user", "reviewed_by")
    readonly_fields = ("created_at", "updated_at", "reviewed_by", "reviewed_at")
    autocomplete_fields = ("user",)
    actions = ("mark_approved", "mark_rejected")

    fieldsets = (
        ("متقاضی", {"fields": ("user", "contact_name", "contact_phone", "contact_email", "national_id")}),
        ("کسب‌وکار", {"fields": ("store_name", "seller_type", "province", "city", "postal_code", "address", "website_or_social", "description")}),
        ("بررسی مدیر", {"fields": ("status", "reviewer_note", "reviewed_by", "reviewed_at", "created_at", "updated_at")}),
    )

    def save_model(self, request, obj, form, change):
        if obj.user_id:
            from apps.users.models import User
            try:
                submitted_phone = str(User.objects.normalize_phone(obj.contact_phone))
            except ValueError as exc:
                raise ValidationError("شماره تماس درخواست معتبر نیست؛ قبل از اتصال حساب آن را اصلاح کن.") from exc
            if str(obj.user.phone) != submitted_phone:
                raise ValidationError("شماره تلفن حساب انتخاب‌شده با شماره تماس درخواست فروشندگی یکسان نیست.")
            if obj.contact_email and obj.user.email and obj.contact_email.casefold() != obj.user.email.casefold():
                raise ValidationError("ایمیل حساب انتخاب‌شده با ایمیل درخواست فروشندگی یکسان نیست.")
        super().save_model(request, obj, form, change)

    @admin.action(description="تأیید درخواست (ایجاد حساب و نقش فروشنده به‌صورت دستی)")
    def mark_approved(self, request, queryset):
        from django.utils import timezone
        updated = queryset.filter(status=VendorApplication.Status.PENDING).update(
            status=VendorApplication.Status.APPROVED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"{updated} درخواست تأیید شد. اکنون حساب کاربر را طبق روال مدیریتی ایجاد/تکمیل و نقش مدیر فروشگاه را دستی تنظیم کنید؛ این اقدام به‌تنهایی دسترسی پنل ایجاد نمی‌کند.")

    @admin.action(description="رد درخواست‌های انتخاب‌شده")
    def mark_rejected(self, request, queryset):
        from django.utils import timezone
        updated = queryset.filter(status=VendorApplication.Status.PENDING).update(
            status=VendorApplication.Status.REJECTED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"{updated} درخواست رد شد.")


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("store_name", "user", "seller_type", "status_badge", "commission_bps", "supports_custom_printing", "created_at")
    list_filter = ("status", "seller_type", "supports_custom_printing", "created_at")
    search_fields = ("store_name", "slug", "user__phone", "user__email")
    autocomplete_fields = ("user",)
    readonly_fields = ("uuid", "created_at", "updated_at", "approved_at", "bank_details_verified_at")
    list_select_related = ("user",)
    actions = ("approve_vendors", "suspend_vendors", "verify_bank_details")

    @admin.display(description="وضعیت")
    def status_badge(self, obj):
        css = {Vendor.Status.ACTIVE: "success", Vendor.Status.PENDING: "warning", Vendor.Status.SUSPENDED: "danger"}.get(obj.status, "secondary")
        return format_html('<span class="badge badge-{}">{}</span>', css, obj.get_status_display())

    @admin.action(description="تأیید فروشندگان انتخاب‌شده")
    def approve_vendors(self, request, queryset):
        from django.utils import timezone
        updated = queryset.filter(status=Vendor.Status.PENDING).update(status=Vendor.Status.ACTIVE, approved_at=timezone.now())
        self.message_user(request, f"{updated} فروشنده تأیید شد.")

    @admin.action(description="تأیید اطلاعات بانکی فروشندگان انتخاب‌شده")
    def verify_bank_details(self, request, queryset):
        from django.utils import timezone
        from django.contrib import messages
        from django.core.exceptions import ValidationError
        count = 0
        invalid = 0
        for vendor in queryset:
            try:
                vendor.full_clean()
            except ValidationError:
                invalid += 1
                continue
            if not vendor.bank_iban or not vendor.bank_account_name:
                invalid += 1
                continue
            vendor.bank_details_verified_at = timezone.now()
            vendor.save(update_fields=("bank_details_verified_at", "updated_at"))
            count += 1
        if count:
            self.message_user(request, f"اطلاعات بانکی {count} فروشنده علامت‌گذاری شد؛ این اقدام فقط پس از تطبیق واقعی شبا و مالک حساب با مدرک معتبر انجام شود.", messages.WARNING)
        if invalid:
            self.message_user(request, f"اطلاعات بانکی {invalid} فروشنده ناقص یا نامعتبر بود و تأیید نشد.", messages.ERROR)

    @admin.action(description="تعلیق فروشندگان انتخاب‌شده")
    def suspend_vendors(self, request, queryset):
        updated = queryset.exclude(status=Vendor.Status.SUSPENDED).update(status=Vendor.Status.SUSPENDED)
        self.message_user(request, f"{updated} فروشنده تعلیق شد.")


class WholesaleTierInline(admin.TabularInline):
    model = WholesalePriceTier
    extra = 0


@admin.register(VendorProduct)
class VendorProductAdmin(admin.ModelAdmin):
    list_display = ("product", "vendor", "status", "retail_price", "sale_unit", "units_per_order", "stock_quantity", "wholesale_enabled", "supports_custom_printing")
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


@admin.register(ShippingQuote)
class ShippingQuoteAdmin(ReadOnlyAuditAdmin):
    list_display = ("uuid", "user", "cart_item", "vendor_listing", "provider", "amount", "status", "expires_at", "order")
    list_filter = ("provider", "status", "created_at", "expires_at")
    search_fields = ("uuid", "quote_reference", "user__phone", "order__number")
    list_select_related = ("user", "cart_item", "vendor_listing", "order")


@admin.register(Shipment)
class ShipmentAdmin(ReadOnlyAuditAdmin):
    def has_change_permission(self, request, obj=None):
        # Allow the changelist's audited delivery action, but keep the
        # individual shipment form strictly read-only.
        if request.path.rstrip("/").endswith("/change"):
            return False
        return request.user.is_active and request.user.is_staff

    list_display = ("vendor_order", "provider", "status", "tracking_number", "quoted_cost", "actual_cost", "created_at")
    list_filter = ("provider", "status", "payer", "created_at")
    search_fields = ("tracking_number", "external_shipment_id", "vendor_order__order__number", "vendor_order__vendor__store_name")
    readonly_fields = tuple(field.name for field in Shipment._meta.fields)
    list_select_related = ("vendor_order", "vendor_order__vendor", "vendor_order__order")
    actions = ("confirm_delivery_with_evidence",)

    @admin.action(description="تأیید تحویل مرسوله با ثبت مدرک")
    def confirm_delivery_with_evidence(self, request, queryset):
        from django.contrib import messages
        from django.utils import timezone
        from .services import mark_vendor_order_delivered

        if queryset.count() != 1:
            self.message_user(request, "برای ثبت مدرک، هر بار فقط یک مرسوله را انتخاب کن.", messages.ERROR)
            return None

        if request.POST.get("apply"):
            reference = " ".join(str(request.POST.get("delivery_evidence_reference") or "").split())
            note = " ".join(str(request.POST.get("delivery_evidence_note") or "").split())
            if not reference or len(reference) > 180:
                self.message_user(request, "مرجع قابل پیگیری تحویل الزامی است و حداکثر ۱۸۰ نویسه دارد.", messages.ERROR)
                return None
            if len(note) > 1000:
                self.message_user(request, "توضیح مدرک تحویل حداکثر ۱۰۰۰ نویسه باشد.", messages.ERROR)
                return None

            candidate = queryset.first()
            now = timezone.now()
            allowed_statuses = {
                Shipment.Status.BOOKED,
                Shipment.Status.PICKUP_REQUESTED,
                Shipment.Status.HANDED_OVER,
                Shipment.Status.IN_TRANSIT,
                Shipment.Status.EXCEPTION,
                Shipment.Status.DELIVERY_FAILED,
            }
            with transaction.atomic():
                # Match refund/booking lock order: vendor order, then shipment.
                vendor_order = VendorOrder.objects.select_for_update().get(pk=candidate.vendor_order_id)
                shipment = Shipment.objects.select_for_update().get(pk=candidate.pk, vendor_order=vendor_order)
                if shipment.status not in allowed_statuses:
                    self.message_user(request, "این مرسوله در وضعیت قابل تأیید تحویل نیست.", messages.ERROR)
                    return None
                if vendor_order.status in {VendorOrder.Status.CANCELLED, VendorOrder.Status.DISPUTED}:
                    self.message_user(request, "سفارش لغوشده یا دارای اختلاف باید ابتدا از مسیر رسمی بررسی شود.", messages.ERROR)
                    return None
                shipment.status = Shipment.Status.DELIVERED
                shipment.delivered_at = now
                payload = shipment.provider_payload if isinstance(shipment.provider_payload, dict) else {}
                shipment.provider_payload = {
                    **payload,
                    "delivery_confirmation": {
                        "source": "staff_manual",
                        "reference": reference,
                        "note": note,
                        "confirmed_by_user_id": request.user.pk,
                        "confirmed_at": now.isoformat(),
                    },
                }
                shipment.last_event_at = now
                shipment.last_error = ""
                shipment.save(update_fields=(
                    "status", "delivered_at", "provider_payload", "last_event_at",
                    "last_error", "updated_at",
                ))
                all_parcels_delivered = not Shipment.objects.filter(
                    vendor_order_id=vendor_order.pk,
                ).exclude(status=Shipment.Status.DELIVERED).exists()
                if all_parcels_delivered:
                    mark_vendor_order_delivered(vendor_order, delivered_at=now)

            self.message_user(request, "تحویل ثبت شد و مدرک در سابقه مرسوله ذخیره شد.", messages.SUCCESS)
            return None

        return TemplateResponse(request, "admin/marketplace/shipment/confirm_delivery.html", {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "queryset": queryset,
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            "selected_ids": list(queryset.values_list("pk", flat=True)),
            "title": "تأیید تحویل مرسوله",
        })


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
    actions = ("approve_and_submit_selected", "reopen_failed_for_retry")

    def has_change_permission(self, request, obj=None):
        # Keep all fields read-only while allowing the explicit approval action.
        return request.user.is_active and request.user.is_staff

    @admin.action(description="پس از بررسی پنل بانک، آماده‌سازی مجدد تسویه ناموفق")
    def reopen_failed_for_retry(self, request, queryset):
        from django.contrib import messages
        from django.db import transaction
        reopened = 0
        blocked = 0
        for batch in queryset:
            with transaction.atomic():
                locked = SettlementBatch.objects.select_for_update().get(pk=batch.pk)
                if locked.status != SettlementBatch.Status.FAILED:
                    blocked += 1
                    continue
                locked.status = SettlementBatch.Status.APPROVED
                locked.failure_reason = "پس از بررسی دستی تأیید شد که واریز قبلی انجام نشده است؛ آماده ارسال مجدد."
                locked.save(update_fields=("status", "failure_reason"))
                reopened += 1
        if reopened:
            self.message_user(request, f"{reopened} تسویه برای ارسال مجدد آماده شد. حالا اقدام تأیید و ارسال را اجرا کن.", messages.WARNING)
        if blocked:
            self.message_user(request, f"{blocked} مورد به‌دلیل وضعیت غیرقابل‌بازگشایی بود.", messages.ERROR)

    @admin.action(description="تأیید و ارسال تسویه‌های انتخاب‌شده برای واریز")
    def approve_and_submit_selected(self, request, queryset):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied, ValidationError
        from .services import approve_settlement
        from .payouts import PayoutError, PayoutNotConfigured, submit_settlement_payout
        approved = 0
        submitted = 0
        errors = []
        for batch in queryset:
            try:
                if batch.status == SettlementBatch.Status.PENDING_APPROVAL:
                    approve_settlement(batch_id=batch.pk, approver=request.user)
                    approved += 1
                refreshed = SettlementBatch.objects.get(pk=batch.pk)
                if refreshed.status == SettlementBatch.Status.APPROVED:
                    submit_settlement_payout(refreshed.pk)
                    submitted += 1
            except PayoutNotConfigured:
                errors.append(f"تسویه {batch.pk}: سرویس واریز پیکربندی نشده است؛ فقط تأیید ثبت شد.")
            except (PermissionDenied, ValidationError, PayoutError) as exc:
                errors.append(f"تسویه {batch.pk}: {str(exc)}")
        if approved:
            self.message_user(request, f"{approved} تسویه تأیید شد.", messages.SUCCESS)
        if submitted:
            self.message_user(request, f"{submitted} درخواست واریز به سرویس مالی ارسال شد.", messages.SUCCESS)
        for error in errors[:10]:
            self.message_user(request, error, messages.WARNING)


@admin.register(SettlementLine)
class SettlementLineAdmin(ReadOnlyAuditAdmin):
    list_display = ("batch", "vendor_order", "gross_amount", "commission_amount", "payable_amount")
    list_select_related = ("batch", "vendor_order")



@admin.register(FinancialReconciliation)
class FinancialReconciliationAdmin(ReadOnlyAuditAdmin):
    list_display = ("source", "external_reference", "internal_reference", "expected_amount", "actual_amount", "status", "currency", "reconciled_at")
    list_filter = ("source", "status", "currency", "created_at")
    search_fields = ("external_reference", "internal_reference")
    list_select_related = ("recorded_by",)



@admin.register(VendorProductSubmission)
class VendorProductSubmissionAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "category", "retail_price", "sale_unit", "units_per_order", "stock_quantity", "weight_grams", "status", "created_at")
    list_filter = ("status", "category", "created_at")
    search_fields = ("name", "vendor__store_name", "category__name")
    autocomplete_fields = ("vendor", "category", "product")
    readonly_fields = ("status", "listing", "reviewed_by", "reviewed_at", "created_at", "updated_at")
    actions = ("approve_product_submissions", "reject_product_submissions")

    @admin.action(description="تأیید محصول و ایجاد کالا و آگهی فروش")
    def approve_product_submissions(self, request, queryset):
        from django.contrib import messages
        from django.utils import timezone

        approved = 0
        errors = []
        for submission in queryset.filter(status=VendorProductSubmission.Status.PENDING):
            try:
                with transaction.atomic():
                    locked = VendorProductSubmission.objects.select_for_update().select_related(
                        "vendor", "category"
                    ).get(pk=submission.pk)
                    if locked.status != VendorProductSubmission.Status.PENDING:
                        continue
                    if not locked.vendor.can_receive_orders:
                        raise ValidationError("فروشنده فعال نیست.")
                    locked.full_clean()
                    product = locked.product
                    if product is not None:
                        if product.category_id != locked.category_id:
                            raise ValidationError("دسته‌بندی محصول موجود با دسته‌بندی درخواست فروشنده یکسان نیست.")
                    else:
                        duplicate = Product.objects.filter(
                            category_id=locked.category_id,
                            name__iexact=locked.name,
                        ).first()
                        if duplicate:
                            raise ValidationError(
                                f"محصولی با همین نام در این دسته وجود دارد (شناسه {duplicate.pk}). "
                                "ابتدا محصول موجود را در فیلد «محصول کاتالوگ» انتخاب کن و دوباره تأیید کن."
                            )
                        base_slug = slugify(locked.name, allow_unicode=True) or f"product-{locked.pk}"
                        slug = base_slug
                        if Product.objects.filter(slug=slug).exists():
                            slug = f"{base_slug}-{locked.pk}"
                        suffix = 2
                        while Product.objects.filter(slug=slug).exists():
                            slug = f"{base_slug}-{locked.pk}-{suffix}"
                            suffix += 1
                        product = Product.objects.create(
                            category=locked.category,
                            name=locked.name,
                            slug=slug,
                            short_description=locked.short_description,
                            description=locked.description,
                            base_price=locked.retail_price,
                            compare_at_price=locked.compare_at_price,
                            marketplace_only=True,
                            is_active=True,
                        )
                        ProductImage.objects.create(
                            product=product,
                            image=locked.image,
                            alt_text=locked.name[:180],
                            image_type=ProductImage.ImageType.PRIMARY,
                        )
                    if VendorProduct.objects.filter(vendor=locked.vendor, product=product).exists():
                        raise ValidationError("این فروشگاه از قبل برای همین محصول آگهی فروش دارد.")
                    listing = VendorProduct(
                        vendor=locked.vendor,
                        product=product,
                        status=VendorProduct.Status.ACTIVE,
                        retail_price=locked.retail_price,
                        compare_at_price=locked.compare_at_price,
                        sale_unit=locked.sale_unit,
                        units_per_order=locked.units_per_order,
                        stock_quantity=locked.stock_quantity,
                        weight_grams=locked.weight_grams,
                        package_length_cm=locked.package_length_cm,
                        package_width_cm=locked.package_width_cm,
                        package_height_cm=locked.package_height_cm,
                        handling_days=locked.handling_days,
                        supports_custom_printing=locked.supports_custom_printing,
                    )
                    listing.full_clean()
                    listing.save()
                    locked.status = VendorProductSubmission.Status.APPROVED
                    locked.product = product
                    locked.listing = listing
                    locked.reviewed_by = request.user
                    locked.reviewed_at = timezone.now()
                    locked.reviewer_note = locked.reviewer_note or "محصول و آگهی فروش تأیید شدند."
                    locked.save(update_fields=(
                        "status", "product", "listing", "reviewed_by", "reviewed_at",
                        "reviewer_note", "updated_at",
                    ))
                    approved += 1
            except (ValidationError, ValueError, IntegrityError) as exc:
                VendorProductSubmission.objects.filter(
                    pk=submission.pk,
                    status=VendorProductSubmission.Status.PENDING,
                ).update(reviewer_note=f"نیاز به بررسی/اصلاح: {exc}"[:4000])
                errors.append(f"درخواست {submission.pk}: {exc}")
        if approved:
            self.message_user(request, f"{approved} محصول تأیید و برای فروش فعال شد.", messages.SUCCESS)
        for error in errors[:10]:
            self.message_user(request, error, messages.ERROR)

    @admin.action(description="رد درخواست‌های ثبت محصول")
    def reject_product_submissions(self, request, queryset):
        from django.utils import timezone
        from django.contrib import messages
        updated = queryset.filter(status=VendorProductSubmission.Status.PENDING).update(
            status=VendorProductSubmission.Status.REJECTED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        
        )
        self.message_user(request, f"{updated} درخواست ثبت محصول رد شد.", messages.WARNING)


@admin.register(CategoryRequest)
class CategoryRequestAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "status", "reviewed_by", "created_at", "reviewed_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "vendor__store_name", "description")
    list_select_related = ("vendor", "reviewed_by")
    readonly_fields = ("created_at", "reviewed_at", "reviewed_by")
    actions = ("approve_requests", "reject_requests")

    @admin.action(description="تأیید درخواست‌ها و ایجاد دسته‌بندی")
    def approve_requests(self, request, queryset):
        from django.utils import timezone

        created_categories = 0
        approved_requests = 0
        with transaction.atomic():
            pending = queryset.select_for_update().filter(status=CategoryRequest.Status.PENDING)
            for category_request in pending:
                category = Category.objects.filter(name__iexact=category_request.name).first()
                if category is None:
                    base_slug = slugify(category_request.name, allow_unicode=True) or f"category-{category_request.pk}"
                    candidate = base_slug[:150]
                    suffix = 2
                    while Category.objects.filter(slug=candidate).exists():
                        tail = f"-{suffix}"
                        candidate = f"{base_slug[:150-len(tail)]}{tail}"
                        suffix += 1
                    category = Category.objects.create(
                        name=category_request.name,
                        slug=candidate,
                        description=category_request.description,
                        is_active=True,
                    )
                    created_categories += 1
                category_request.status = CategoryRequest.Status.APPROVED
                category_request.reviewed_by = request.user
                category_request.reviewed_at = timezone.now()
                category_request.save(update_fields=("status", "reviewed_by", "reviewed_at"))
                approved_requests += 1
        self.message_user(
            request,
            f"{approved_requests} درخواست تأیید شد؛ {created_categories} دسته‌بندی جدید ایجاد شد.",
        )

    @admin.action(description="رد درخواست‌های دسته‌بندی")
    def reject_requests(self, request, queryset):
        from django.utils import timezone
        updated = queryset.filter(status=CategoryRequest.Status.PENDING).update(
            status=CategoryRequest.Status.REJECTED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"{updated} درخواست رد شد.")
