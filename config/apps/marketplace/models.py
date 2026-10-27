from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Vendor(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار بررسی"
        ACTIVE = "active", "فعال"
        SUSPENDED = "suspended", "تعلیق‌شده"
        REJECTED = "rejected", "ردشده"

    class SellerType(models.TextChoices):
        RETAIL = "retail", "خرده‌فروشی"
        WHOLESALE = "wholesale", "عمده‌فروشی"
        BOTH = "both", "خرده‌فروشی و عمده‌فروشی"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="vendor_profile")
    store_name = models.CharField(max_length=160)
    seller_type = models.CharField(max_length=12, choices=SellerType.choices, default=SellerType.RETAIL)
    slug = models.SlugField(max_length=180, unique=True, allow_unicode=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    commission_bps = models.PositiveSmallIntegerField(default=1000, validators=[MaxValueValidator(10000)], help_text="کمیسیون بر حسب basis point؛ 1000 یعنی 10 درصد.")
    supports_custom_printing = models.BooleanField(default=False)
    settlement_hold_hours = models.PositiveSmallIntegerField(default=24, validators=[MinValueValidator(24)], help_text="حداقل فاصله تحویل تا واجد شرایط شدن برای تسویه؛ کمتر از ۲۴ ساعت مجاز نیست.")
    bank_account_name = models.CharField(max_length=160, blank=True)
    bank_iban = models.CharField(max_length=34, blank=True, help_text="اطلاعات بانکی فقط پس از احراز هویت و با دسترسی محدود نگهداری شود.")
    pickup_postal_code = models.CharField(max_length=10, blank=True)
    pickup_address = models.TextField(blank=True)
    pickup_city = models.CharField(max_length=120, blank=True)
    pickup_province = models.CharField(max_length=120, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    bank_details_verified_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("store_name",)
        constraints = [
            models.CheckConstraint(check=Q(commission_bps__lte=10000), name="vendor_commission_bps_lte_10000"),
            models.CheckConstraint(check=Q(settlement_hold_hours__gte=24), name="vendor_settlement_hold_gte_24h"),
        ]
        indexes = [models.Index(fields=("status", "created_at"), name="market_vendor_status_idx")]

    def clean(self):
        super().clean()
        self.store_name = " ".join((self.store_name or "").split())
        self.slug = (self.slug or "").strip().lower()
        self.bank_account_name = " ".join((self.bank_account_name or "").split())
        iban = "".join((self.bank_iban or "").split()).upper()
        self.bank_iban = iban
        if bool(iban) != bool(self.bank_account_name):
            raise ValidationError({
                "bank_iban": "برای ثبت اطلاعات بانکی، نام صاحب حساب و شماره شبا باید هر دو وارد شوند."
            })
        if iban:
            if len(iban) != 26 or not iban.startswith("IR") or not iban[2:].isdigit():
                raise ValidationError({"bank_iban": "شماره شبای ایران باید با IR و ۲۴ رقم ادامه پیدا کند."})
            rearranged = iban[4:] + iban[:4]
            remainder = 0
            for char in rearranged:
                digits = str(ord(char) - 55) if char.isalpha() else char
                for digit in digits:
                    remainder = (remainder * 10 + int(digit)) % 97
            if remainder != 1:
                raise ValidationError({"bank_iban": "شماره شبا از نظر checksum معتبر نیست."})

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values("bank_iban", "bank_account_name").first()
            if old and (
                old["bank_iban"] != self.bank_iban
                or old["bank_account_name"] != self.bank_account_name
            ):
                self.bank_details_verified_at = None
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {"bank_details_verified_at"}
        super().save(*args, **kwargs)

    @property
    def can_receive_orders(self):
        return self.status == self.Status.ACTIVE and self.user.is_active

    def __str__(self):
        return self.store_name


class VendorProduct(models.Model):
    class SaleType(models.TextChoices):
        RETAIL = "retail", "فقط تکی"
        WHOLESALE = "wholesale", "فقط عمده"
        BOTH = "both", "تکی و عمده"

    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        PENDING = "pending", "در انتظار تأیید"
        ACTIVE = "active", "فعال"
        PAUSED = "paused", "متوقف"
        REJECTED = "rejected", "ردشده"

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="listings")
    product = models.ForeignKey("shop.Product", on_delete=models.PROTECT, related_name="vendor_listings")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    sale_type = models.CharField(max_length=12, choices=SaleType.choices, default=SaleType.RETAIL)
    retail_price = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    compare_at_price = models.PositiveBigIntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    sale_unit = models.CharField(max_length=40, default="عدد", help_text="واحد قابل سفارش؛ مثل عدد یا جعبه ۱۲تایی.")
    units_per_order = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)], help_text="تعداد اقلام فیزیکی در هر واحد فروش.")
    stock_quantity = models.PositiveIntegerField(default=0)
    weight_grams = models.PositiveIntegerField(default=0, help_text="وزن بسته‌بندی‌شده بر حسب گرم؛ برای استعلام حمل الزامی است.")
    package_length_cm = models.PositiveSmallIntegerField(default=0)
    package_width_cm = models.PositiveSmallIntegerField(default=0)
    package_height_cm = models.PositiveSmallIntegerField(default=0)
    wholesale_enabled = models.BooleanField(default=False)
    supports_custom_printing = models.BooleanField(default=False)
    handling_days = models.PositiveSmallIntegerField(default=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("vendor", "product"), name="unique_vendor_product_listing"),
            models.CheckConstraint(check=Q(retail_price__gt=0), name="vendor_listing_price_gt_zero"),
            models.CheckConstraint(check=Q(compare_at_price__isnull=True) | Q(compare_at_price__gte=models.F("retail_price")), name="vendor_listing_compare_gte_retail"),
            models.CheckConstraint(check=Q(units_per_order__gt=0), name="vendor_listing_units_per_order_gt_zero"),
        ]
        indexes = [models.Index(fields=("vendor", "status"), name="market_listing_v_status_idx")]

    def clean(self):
        super().clean()
        self.sale_unit = " ".join((self.sale_unit or "").split())
        if not self.sale_unit:
            raise ValidationError({"sale_unit": "واحد فروش را وارد کن."})
        if self.units_per_order < 1:
            raise ValidationError({"units_per_order": "تعداد اقلام در هر واحد فروش باید حداقل ۱ باشد."})
        if self.compare_at_price is not None and self.compare_at_price < self.retail_price:
            raise ValidationError({"compare_at_price": "قیمت قبل از تخفیف باید از قیمت فروش بیشتر یا مساوی باشد."})
        if self.sale_type in {self.SaleType.WHOLESALE, self.SaleType.BOTH} and self.vendor.seller_type == Vendor.SellerType.RETAIL:
            raise ValidationError({"sale_type": "این فروشگاه فقط مجوز خرده‌فروشی دارد."})
        if self.sale_type == self.SaleType.RETAIL and self.wholesale_enabled:
            raise ValidationError({"sale_type": "برای فروش تکی، فروش عمده باید غیرفعال باشد."})
        if self.pk and self.sale_type in {self.SaleType.WHOLESALE, self.SaleType.BOTH} and not self.wholesale_tiers.exists():
            raise ValidationError({"sale_type": "برای فعال‌کردن فروش عمده، حداقل یک پله قیمت عمده لازم است."})
        if self.wholesale_enabled and self.vendor.seller_type == Vendor.SellerType.RETAIL:
            raise ValidationError({"wholesale_enabled": "فروشگاه شما برای فروش عمده تأیید نشده است."})
        if self.supports_custom_printing and not self.vendor.supports_custom_printing:
            raise ValidationError({"supports_custom_printing": "فروشنده هنوز دسترسی چاپ سفارشی ندارد."})
        if self.wholesale_enabled and not self.pk:
            raise ValidationError({
                "wholesale_enabled": "ابتدا آگهی را بدون فروش عمده ثبت کن؛ پس از ذخیره، پله‌های قیمت عمده را اضافه کن."
            })
        if self.pk and self.wholesale_enabled and not self.wholesale_tiers.exists():
            raise ValidationError({
                "wholesale_enabled": "برای فعال‌کردن فروش عمده، حداقل یک پله قیمت عمده ثبت کن."
            })
        if self.pk and self.wholesale_tiers.filter(unit_price__gt=self.retail_price).exists():
            raise ValidationError({
                "retail_price": "قیمت خرده‌فروشی نمی‌تواند کمتر از قیمت هیچ‌یک از پله‌های عمده باشد."
            })

    def __str__(self):
        return f"{self.vendor.store_name} — {self.product}"


class WholesalePriceTier(models.Model):
    listing = models.ForeignKey(VendorProduct, on_delete=models.CASCADE, related_name="wholesale_tiers")
    minimum_quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("minimum_quantity",)
        constraints = [
            models.UniqueConstraint(fields=("listing", "minimum_quantity"), name="unique_wholesale_quantity_tier"),
            models.CheckConstraint(check=Q(minimum_quantity__gte=1), name="wholesale_min_qty_gte_one"),
            models.CheckConstraint(check=Q(unit_price__gt=0), name="wholesale_unit_price_gt_zero"),
        ]

    def clean(self):
        super().clean()
        if self.listing_id:
            if self.listing.vendor.seller_type == Vendor.SellerType.RETAIL:
                raise ValidationError({"listing": "فروش عمده برای این فروشگاه تأیید نشده است."})
            if self.unit_price > self.listing.retail_price:
                raise ValidationError({"unit_price": "قیمت عمده نباید از قیمت خرده‌فروشی بیشتر باشد."})
            existing = type(self).objects.filter(listing_id=self.listing_id)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.filter(minimum_quantity__lt=self.minimum_quantity, unit_price__lt=self.unit_price).exists():
                raise ValidationError({
                    "unit_price": "با افزایش حداقل تعداد، قیمت واحد عمده نباید از پله تعداد کمتر بیشتر شود."
                })
            if existing.filter(minimum_quantity__gt=self.minimum_quantity, unit_price__gt=self.unit_price).exists():
                raise ValidationError({
                    "unit_price": "قیمت این پله نباید از قیمت پله‌های تعداد بالاتر بیشتر باشد."
                })

    def __str__(self):
        return f"{self.listing} / {self.minimum_quantity}+"


class VendorOrder(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "جدید"
        ACCEPTED = "accepted", "تأیید فروشنده"
        PREPARING = "preparing", "در حال آماده‌سازی"
        READY_TO_SHIP = "ready_to_ship", "آماده ارسال"
        SHIPPED = "shipped", "ارسال‌شده"
        DELIVERED = "delivered", "تحویل‌شده"
        CANCELLED = "cancelled", "لغوشده"
        DISPUTED = "disputed", "دارای اختلاف"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="vendor_orders")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    currency = models.CharField(max_length=3, default="IRT")
    items_snapshot = models.JSONField(default=list)
    subtotal = models.PositiveBigIntegerField(default=0)
    customer_shipping_amount = models.PositiveBigIntegerField(default=0)
    commission_amount = models.PositiveBigIntegerField(default=0)
    shipping_cost_actual = models.PositiveBigIntegerField(null=True, blank=True)
    vendor_payable = models.PositiveBigIntegerField(default=0)
    delivered_at = models.DateTimeField(null=True, blank=True)
    settlement_eligible_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("order", "vendor"), name="unique_vendor_order_per_order"),
            models.CheckConstraint(check=Q(vendor_payable__gte=0), name="vendor_order_payable_nonnegative"),
        ]
        indexes = [models.Index(fields=("vendor", "status", "created_at"), name="market_vorder_v_status_idx")]

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values(
                "order_id", "vendor_id", "currency", "items_snapshot", "subtotal",
                "customer_shipping_amount", "commission_amount", "vendor_payable",
            ).first()
            current = {
                "order_id": self.order_id,
                "vendor_id": self.vendor_id,
                "currency": self.currency,
                "items_snapshot": self.items_snapshot,
                "subtotal": self.subtotal,
                "customer_shipping_amount": self.customer_shipping_amount,
                "commission_amount": self.commission_amount,
                "vendor_payable": self.vendor_payable,
            }
            if old and old != current:
                raise ValidationError("اطلاعات مالی و Snapshot سفارش فروشنده قابل بازنویسی نیست.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("سفارش فروشنده حذف نمی‌شود؛ از گردش لغو/بازپرداخت استفاده کنید.")

    def __str__(self):
        return f"{self.order.number} / {self.vendor.store_name}"


class ShippingQuote(models.Model):
    class Status(models.TextChoices):
        VALID = "valid", "معتبر"
        CONSUMED = "consumed", "استفاده‌شده"
        EXPIRED = "expired", "منقضی‌شده"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="marketplace_shipping_quotes")
    cart_item = models.ForeignKey("orders.CartItem", on_delete=models.PROTECT, related_name="shipping_quotes")
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="shipping_quotes", null=True, blank=True)
    vendor_listing = models.ForeignKey(VendorProduct, on_delete=models.PROTECT, related_name="shipping_quotes")
    provider = models.CharField(max_length=16, choices=[("tipax", "تیپاکس"), ("post", "شرکت ملی پست")])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.VALID, db_index=True)
    amount = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="IRT")
    quote_reference = models.CharField(max_length=160, blank=True)
    quantity = models.PositiveIntegerField()
    address_fingerprint = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    provider_payload = models.JSONField(default=dict, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("user", "status", "expires_at"), name="market_quote_user_status_idx")]

    def __str__(self):
        return f"{self.provider} / {self.amount} / {self.uuid}"


class Shipment(models.Model):
    class Provider(models.TextChoices):
        TIPAX = "tipax", "تیپاکس"
        POST = "post", "شرکت ملی پست"
        MANUAL = "manual", "ثبت دستی"
        OTHER = "other", "سایر"

    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        QUOTED = "quoted", "هزینه برآورد شد"
        BOOKED = "booked", "مرسوله ثبت شد"
        PICKUP_REQUESTED = "pickup_requested", "درخواست جمع‌آوری"
        HANDED_OVER = "handed_over", "تحویل شرکت حمل"
        IN_TRANSIT = "in_transit", "در مسیر"
        DELIVERED = "delivered", "تحویل‌شده"
        DELIVERY_FAILED = "delivery_failed", "تحویل ناموفق"
        RETURNED = "returned", "مرجوع‌شده"
        CANCELLED = "cancelled", "لغوشده"
        EXCEPTION = "exception", "نیازمند بررسی"

    class Payer(models.TextChoices):
        PLATFORM = "platform", "سایت"
        VENDOR = "vendor", "فروشنده"
        RECIPIENT = "recipient", "گیرنده"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    vendor_order = models.ForeignKey(VendorOrder, on_delete=models.PROTECT, related_name="shipments")
    provider = models.CharField(max_length=16, choices=Provider.choices, default=Provider.MANUAL)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    payer = models.CharField(max_length=16, choices=Payer.choices, default=Payer.PLATFORM)
    external_shipment_id = models.CharField(max_length=160, blank=True, db_index=True)
    tracking_number = models.CharField(max_length=160, blank=True, db_index=True)
    label_url = models.URLField(max_length=1000, blank=True)
    quoted_cost = models.PositiveBigIntegerField(null=True, blank=True)
    actual_cost = models.PositiveBigIntegerField(null=True, blank=True)
    customer_charge = models.PositiveBigIntegerField(default=0)
    quote_reference = models.CharField(max_length=160, blank=True)
    quote_expires_at = models.DateTimeField(null=True, blank=True)
    booked_at = models.DateTimeField(null=True, blank=True)
    handed_over_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    provider_payload = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("provider", "status", "created_at"), name="market_ship_p_status_idx"),
            models.Index(fields=("vendor_order", "status"), name="market_ship_order_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=("provider", "external_shipment_id"), condition=~Q(external_shipment_id=""), name="unique_provider_shipment_id"),
            models.UniqueConstraint(fields=("provider", "tracking_number"), condition=~Q(tracking_number=""), name="unique_provider_tracking"),
        ]

    def __str__(self):
        return self.tracking_number or f"{self.provider}:{self.uuid}"


class LedgerAccount(models.Model):
    class Kind(models.TextChoices):
        ASSET = "asset", "دارایی"
        LIABILITY = "liability", "بدهی"
        REVENUE = "revenue", "درآمد"
        EXPENSE = "expense", "هزینه"
        EQUITY = "equity", "حقوق مالکانه"

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="ledger_accounts", null=True, blank=True)
    currency = models.CharField(max_length=3, default="IRT")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("vendor", "name", "currency"), name="unique_vendor_ledger_account_name_currency"),
        ]
        ordering = ("code",)

    def __str__(self):
        return f"{self.code} — {self.name}"


class JournalEntry(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        POSTED = "posted", "ثبت قطعی"
        REVERSED = "reversed", "معکوس‌شده"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    idempotency_key = models.CharField(max_length=180, unique=True)
    kind = models.CharField(max_length=48, db_index=True)
    description = models.CharField(max_length=500)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="journal_entries", null=True, blank=True)
    vendor_order = models.ForeignKey(VendorOrder, on_delete=models.PROTECT, related_name="journal_entries", null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="marketplace_journal_entries", null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("kind", "created_at"), name="market_journal_kind_date_idx")]

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if old in {self.Status.POSTED, self.Status.REVERSED}:
                raise ValidationError("سند قطعی قابل ویرایش نیست؛ برای اصلاح باید سند معکوس ثبت شود.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in {self.Status.POSTED, self.Status.REVERSED}:
            raise ValidationError("سند قطعی قابل حذف نیست.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.kind}: {self.idempotency_key}"


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="lines")
    debit = models.PositiveBigIntegerField(default=0)
    credit = models.PositiveBigIntegerField(default=0)
    currency = models.CharField(max_length=3, default="IRT")
    memo = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=(Q(debit__gt=0, credit=0) | Q(credit__gt=0, debit=0)), name="journal_line_one_sided_positive"),
        ]
        indexes = [models.Index(fields=("account", "id"), name="market_jline_account_idx")]

    def save(self, *args, **kwargs):
        if self.entry_id and self.entry.status in {JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED}:
            raise ValidationError("ردیف سند قطعی قابل ویرایش نیست.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.entry.status in {JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED}:
            raise ValidationError("ردیف سند قطعی قابل حذف نیست.")
        return super().delete(*args, **kwargs)


class SettlementBatch(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        PENDING_APPROVAL = "pending_approval", "در انتظار تأیید مدیر"
        APPROVED = "approved", "تأییدشده"
        PROCESSING = "processing", "در حال پرداخت"
        PAID = "paid", "پرداخت‌شده"
        FAILED = "failed", "ناموفق"
        CANCELLED = "cancelled", "لغوشده"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    idempotency_key = models.CharField(max_length=180, unique=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="settlements")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    currency = models.CharField(max_length=3, default="IRT")
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    gross_amount = models.PositiveBigIntegerField(default=0)
    commission_amount = models.PositiveBigIntegerField(default=0)
    shipping_adjustment = models.BigIntegerField(default=0)
    refund_adjustment = models.BigIntegerField(default=0)
    other_adjustment = models.BigIntegerField(default=0)
    payable_amount = models.PositiveBigIntegerField(default=0)
    order_ids = models.JSONField(default=list)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approved_vendor_settlements", null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    payout_reference = models.CharField(max_length=180, blank=True)
    payout_attempts = models.PositiveSmallIntegerField(default=0)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("payout_reference",),
                condition=~Q(payout_reference=""),
                name="unique_settlement_payout_reference",
            ),
        ]
        indexes = [models.Index(fields=("vendor", "status", "created_at"), name="market_settle_v_status_idx")]

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values(
                "status", "idempotency_key", "vendor_id", "currency", "period_start", "period_end",
                "gross_amount", "commission_amount", "shipping_adjustment", "refund_adjustment",
                "other_adjustment", "payable_amount", "order_ids",
            ).first()
            if old and old["status"] != self.Status.DRAFT:
                current = {
                    "status": old["status"],
                    "idempotency_key": self.idempotency_key,
                    "vendor_id": self.vendor_id,
                    "currency": self.currency,
                    "period_start": self.period_start,
                    "period_end": self.period_end,
                    "gross_amount": self.gross_amount,
                    "commission_amount": self.commission_amount,
                    "shipping_adjustment": self.shipping_adjustment,
                    "refund_adjustment": self.refund_adjustment,
                    "other_adjustment": self.other_adjustment,
                    "payable_amount": self.payable_amount,
                    "order_ids": self.order_ids,
                }
                if old != current:
                    raise ValidationError("Snapshot مالی تسویه پس از ارسال برای تأیید قابل تغییر نیست.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValidationError("تسویه پس از ارسال برای تأیید قابل حذف نیست.")
        return super().delete(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.period_end <= self.period_start:
            raise ValidationError({"period_end": "پایان بازه باید بعد از شروع آن باشد."})
        calculated = self.gross_amount - self.commission_amount + self.shipping_adjustment + self.refund_adjustment + self.other_adjustment
        if calculated < 0:
            raise ValidationError({"payable_amount": "مبلغ قابل پرداخت نمی‌تواند منفی باشد."})
        if self.payable_amount != calculated:
            raise ValidationError({
                "payable_amount": "مبلغ قابل پرداخت باید دقیقاً با ناخالص منهای کمیسیون و به‌علاوه تعدیلات برابر باشد."
            })
        if self.payout_attempts < 0:
            raise ValidationError({"payout_attempts": "تعداد تلاش‌های پرداخت نمی‌تواند منفی باشد."})

    def __str__(self):
        return f"{self.vendor.store_name} / {self.uuid}"


class SettlementLine(models.Model):
    batch = models.ForeignKey(SettlementBatch, on_delete=models.PROTECT, related_name="lines")
    vendor_order = models.ForeignKey(VendorOrder, on_delete=models.PROTECT, related_name="settlement_lines")
    gross_amount = models.PositiveBigIntegerField()
    commission_amount = models.PositiveBigIntegerField()
    payable_amount = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("batch", "vendor_order"), name="unique_vendor_order_in_settlement")]
        ordering = ("id",)

    def save(self, *args, **kwargs):
        if self.batch.status != SettlementBatch.Status.DRAFT:
            raise ValidationError("اقلام تسویه پس از ارسال برای تأیید قابل تغییر نیستند.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.batch.status != SettlementBatch.Status.DRAFT:
            raise ValidationError("اقلام تسویه پس از ارسال برای تأیید قابل حذف نیستند.")
        return super().delete(*args, **kwargs)



class FinancialReconciliation(models.Model):
    class Source(models.TextChoices):
        PAYMENT_GATEWAY = "payment_gateway", "درگاه پرداخت"
        BANK_PAYOUT = "bank_payout", "واریز بانکی"
        CARRIER_INVOICE = "carrier_invoice", "صورتحساب حمل"
        BANK_STATEMENT = "bank_statement", "گردش حساب بانکی"
        MANUAL = "manual", "ثبت دستی"

    class Status(models.TextChoices):
        UNMATCHED = "unmatched", "ناقص"
        MATCHED = "matched", "تطبیق‌شده"
        MISMATCH = "mismatch", "دارای مغایرت"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source = models.CharField(max_length=24, choices=Source.choices, db_index=True)
    external_reference = models.CharField(max_length=180)
    internal_reference = models.CharField(max_length=180, blank=True, db_index=True)
    expected_amount = models.BigIntegerField(null=True, blank=True)
    actual_amount = models.BigIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="IRT")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UNMATCHED, db_index=True)
    details = models.JSONField(default=dict, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="marketplace_reconciliations", null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [models.UniqueConstraint(fields=("source", "external_reference"), name="unique_external_reconciliation_ref")]
        indexes = [models.Index(fields=("source", "status", "created_at"), name="market_reconcile_status_idx")]

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values("source", "external_reference", "expected_amount", "actual_amount", "currency", "details", "status").first()
            if old and old["status"] in {self.Status.MATCHED, self.Status.MISMATCH}:
                new = {
                    "source": self.source,
                    "external_reference": self.external_reference,
                    "expected_amount": self.expected_amount,
                    "actual_amount": self.actual_amount,
                    "currency": self.currency,
                    "details": self.details,
                    "status": self.status,
                }
                if old != new:
                    raise ValidationError("سابقه تطبیق مالی قطعی قابل ویرایش نیست؛ یک رکورد اصلاحی جدید ثبت کنید.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in {self.Status.MATCHED, self.Status.MISMATCH}:
            raise ValidationError("سابقه تطبیق مالی قطعی قابل حذف نیست.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.source} / {self.external_reference} / {self.status}"



class CategoryRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار بررسی"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="category_requests")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewer_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reviewed_marketplace_category_requests", null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("status", "created_at"), name="market_category_request_idx")]

    def clean(self):
        super().clean()
        self.name = " ".join((self.name or "").split())
        if len(self.name) < 2:
            raise ValidationError({"name": "نام دسته‌بندی باید حداقل دو نویسه باشد."})

    def __str__(self):
        return f"{self.name} — {self.vendor.store_name}"


class VendorProductSubmission(models.Model):
    class SaleType(models.TextChoices):
        RETAIL = "retail", "فقط تکی"
        WHOLESALE = "wholesale", "فقط عمده"
        BOTH = "both", "تکی و عمده"

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار بررسی"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="product_submissions")
    category = models.ForeignKey("shop.Category", on_delete=models.PROTECT, related_name="vendor_product_submissions")
    name = models.CharField(max_length=200)
    short_description = models.TextField(blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="marketplace/product-submissions/")
    sale_type = models.CharField(max_length=12, choices=SaleType.choices, default=SaleType.RETAIL)
    retail_price = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    compare_at_price = models.PositiveBigIntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    wholesale_minimum_quantity = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    wholesale_unit_price = models.PositiveBigIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    sale_unit = models.CharField(max_length=40, default="عدد",)
    units_per_order = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)],)
    stock_quantity = models.PositiveIntegerField(default=0)
    weight_grams = models.PositiveIntegerField(default=0)
    package_length_cm = models.PositiveSmallIntegerField(default=0)
    package_width_cm = models.PositiveSmallIntegerField(default=0)
    package_height_cm = models.PositiveSmallIntegerField(default=0)
    handling_days = models.PositiveSmallIntegerField(default=2)
    supports_custom_printing = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    product = models.ForeignKey("shop.Product", on_delete=models.PROTECT, related_name="vendor_submissions", null=True, blank=True)
    listing = models.ForeignKey(VendorProduct, on_delete=models.PROTECT, related_name="source_submissions", null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reviewed_vendor_product_submissions", null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(check=Q(retail_price__gt=0), name="vendor_submission_price_gt_zero"),
            models.CheckConstraint(check=Q(compare_at_price__isnull=True) | Q(compare_at_price__gte=models.F("retail_price")), name="vendor_submission_compare_gte_retail"),
            models.CheckConstraint(check=Q(units_per_order__gt=0), name="vendor_submission_units_gt_zero"),
        ]
        indexes = [models.Index(fields=("vendor", "status", "created_at"), name="market_prod_sub_status_idx")]

    def clean(self):
        super().clean()
        self.name = " ".join((self.name or "").split())
        if len(self.name) < 2:
            raise ValidationError({"name": "نام محصول باید حداقل دو نویسه باشد."})
        if self.vendor_id and self.category_id and self.status == self.Status.PENDING:
            duplicates = type(self).objects.filter(
                vendor_id=self.vendor_id,
                category_id=self.category_id,
                name__iexact=self.name,
                status=self.Status.PENDING,
            )
            if self.pk:
                duplicates = duplicates.exclude(pk=self.pk)
            if duplicates.exists():
                raise ValidationError({"name": "درخواست مشابه این محصول قبلاً برای بررسی ارسال شده است."})
        self.sale_unit = " ".join((self.sale_unit or "").split())
        if not self.sale_unit:
            raise ValidationError({"sale_unit": "واحد فروش را وارد کن."})
        if self.units_per_order < 1:
            raise ValidationError({"units_per_order": "تعداد اقلام در هر واحد فروش باید حداقل ۱ باشد."})
        if self.compare_at_price is not None and self.compare_at_price < self.retail_price:
            raise ValidationError({"compare_at_price": "قیمت قبل از تخفیف باید از قیمت فروش بیشتر یا مساوی باشد."})
        if self.sale_type in {self.SaleType.WHOLESALE, self.SaleType.BOTH}:
            if self.wholesale_minimum_quantity is None or self.wholesale_minimum_quantity < 1:
                raise ValidationError({"wholesale_minimum_quantity": "حداقل واحد فروش عمده باید حداقل ۱ باشد."})
            if not self.wholesale_unit_price or self.wholesale_unit_price > self.retail_price:
                raise ValidationError({"wholesale_unit_price": "قیمت واحد عمده باید مثبت و از قیمت نهایی تکی بیشتر نباشد."})
        elif self.wholesale_minimum_quantity or self.wholesale_unit_price:
            raise ValidationError({"sale_type": "برای محصول تکی، اطلاعات قیمت عمده را خالی بگذار."})
        if self.category_id and not self.category.is_active:
            raise ValidationError({"category": "دسته‌بندی انتخاب‌شده فعال نیست."})
        if self.product_id and not self.product.is_active:
            raise ValidationError({"product": "محصول غیرفعال را نمی‌توان برای فروش فعال کرد."})
        if self.product_id and self.product.category_id != self.category_id:
            raise ValidationError({"product": "محصول انتخاب‌شده باید متعلق به همین دسته‌بندی باشد."})
        if self.supports_custom_printing and not self.vendor.supports_custom_printing:
            raise ValidationError({"supports_custom_printing": "فروشگاه هنوز دسترسی چاپ سفارشی ندارد."})

    def __str__(self):
        return f"{self.name} — {self.vendor.store_name} ({self.get_status_display()})"




class VendorApplication(models.Model):
    class SellerType(models.TextChoices):
        RETAIL = "retail", "خرده‌فروشی"
        WHOLESALE = "wholesale", "عمده‌فروشی"
        BOTH = "both", "خرده‌فروشی و عمده‌فروشی"

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار بررسی"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vendor_application",
        null=True,
        blank=True,
    )
    contact_name = models.CharField(max_length=200)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=20)
    national_id = models.CharField(max_length=10, help_text="اطلاعات هویتی محرمانه؛ فقط مدیر مجاز به مشاهده باشد.")
    store_name = models.CharField(max_length=160)
    seller_type = models.CharField(max_length=12, choices=SellerType.choices)
    province = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=10, blank=True)
    address = models.TextField(blank=True)
    website_or_social = models.URLField(max_length=500, blank=True)
    description = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewer_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="reviewed_vendor_applications", null=True, blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("status", "-created_at")
        indexes = [models.Index(fields=("status", "created_at"), name="market_vapp_status_idx")]

    def clean(self):
        super().clean()
        self.contact_name = " ".join((self.contact_name or "").split())
        self.store_name = " ".join((self.store_name or "").split())
        self.national_id = "".join((self.national_id or "").split())
        self.contact_phone = "".join((self.contact_phone or "").split())
        self.postal_code = "".join((self.postal_code or "").split())
        if len(self.national_id) != 10 or not self.national_id.isascii() or not self.national_id.isdigit():
            raise ValidationError({"national_id": "کد ملی باید دقیقاً ۱۰ رقم انگلیسی باشد."})
        if len(set(self.national_id)) == 1:
            raise ValidationError({"national_id": "کد ملی واردشده معتبر نیست."})
        weighted_sum = sum(int(self.national_id[index]) * (10 - index) for index in range(9))
        remainder = weighted_sum % 11
        expected_check_digit = remainder if remainder < 2 else 11 - remainder
        if int(self.national_id[9]) != expected_check_digit:
            raise ValidationError({"national_id": "رقم کنترل کد ملی معتبر نیست."})
        if self.postal_code and (
            len(self.postal_code) != 10 or not self.postal_code.isascii() or not self.postal_code.isdigit()
        ):
            raise ValidationError({"postal_code": "کد پستی باید دقیقاً ۱۰ رقم انگلیسی باشد."})
        if not self.contact_name or not self.store_name or not self.description.strip():
            raise ValidationError("نام متقاضی، نام فروشگاه و توضیحات فعالیت الزامی است.")
        if len(self.description) > 5000:
            raise ValidationError({"description": "توضیحات کسب‌وکار نباید بیشتر از ۵۰۰۰ نویسه باشد."})
        if len(self.address or "") > 2000:
            raise ValidationError({"address": "نشانی نباید بیشتر از ۲۰۰۰ نویسه باشد."})

    def __str__(self):
        return f"{self.store_name} — {self.get_status_display()}"
