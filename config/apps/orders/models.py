from __future__ import annotations

import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class Cart(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "فعال"
        CONVERTED = "converted", "تبدیل‌شده به سفارش"
        ABANDONED = "abandoned", "رهاشده"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="carts",
        null=True,
        blank=True,
    )
    session_key = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user",),
                condition=Q(user__isnull=False, status="active"),
                name="unique_active_cart_per_user",
            ),
            models.UniqueConstraint(
                fields=("session_key",),
                condition=Q(session_key__isnull=False, user__isnull=True, status="active"),
                name="unique_active_guest_cart_per_session",
            ),
        ]
        indexes = [
            models.Index(fields=("user", "status", "updated_at")),
            models.Index(fields=("session_key", "status")),
        ]

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def subtotal(self):
        return sum(item.line_total for item in self.items.all())

    def __str__(self):
        owner = self.user_id or self.session_key or self.uuid
        return f"Cart {owner}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("shop.Product", on_delete=models.PROTECT, related_name="cart_items")
    vendor_listing = models.ForeignKey("marketplace.VendorProduct", on_delete=models.PROTECT, related_name="cart_items", null=True, blank=True)
    variant = models.ForeignKey(
        "shop.ProductVariant",
        on_delete=models.PROTECT,
        related_name="cart_items",
        null=True,
        blank=True,
    )
    custom_design = models.ForeignKey(
        "customizer.DesignDraft",
        on_delete=models.PROTECT,
        related_name="cart_items",
        null=True,
        blank=True,
    )
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("added_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("cart", "variant"),
                condition=Q(variant__isnull=False, custom_design__isnull=True, vendor_listing__isnull=True),
                name="unique_cart_variant_item",
            ),
            models.UniqueConstraint(
                fields=("cart", "variant", "vendor_listing"),
                condition=Q(variant__isnull=False, custom_design__isnull=True, vendor_listing__isnull=False),
                name="unique_cart_vendor_variant_item",
            ),
            models.UniqueConstraint(
                fields=("cart", "product"),
                condition=Q(variant__isnull=True, custom_design__isnull=True, vendor_listing__isnull=True),
                name="unique_cart_product_item",
            ),
            models.UniqueConstraint(
                fields=("cart", "product", "vendor_listing"),
                condition=Q(variant__isnull=True, custom_design__isnull=True, vendor_listing__isnull=False),
                name="unique_cart_vendor_product_item",
            ),
            models.UniqueConstraint(
                fields=("cart", "custom_design"),
                condition=Q(custom_design__isnull=False),
                name="unique_cart_custom_design_item",
            ),
            models.CheckConstraint(check=Q(quantity__gt=0), name="cart_item_quantity_gt_zero"),
        ]
        indexes = [models.Index(fields=("cart", "product")), models.Index(fields=("cart", "variant"))]

    @property
    def unit_price(self):
        if self.custom_design_id:
            return self.custom_design.total_price
        if self.vendor_listing_id:
            price = self.vendor_listing.retail_price
            if self.vendor_listing.wholesale_enabled:
                tier = self.vendor_listing.wholesale_tiers.filter(minimum_quantity__lte=self.quantity).order_by("-minimum_quantity").first()
                if tier:
                    price = tier.unit_price
            return price
        return self.variant.effective_price if self.variant_id else self.product.base_price

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    @property
    def available_stock(self):
        return self.variant.stock_quantity if self.variant_id else None

    def __str__(self):
        return f"{self.product} × {self.quantity}"


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار پرداخت"
        PAID = "paid", "پرداخت‌شده"
        PROCESSING = "processing", "در حال آماده‌سازی"
        SHIPPED = "shipped", "ارسال‌شده"
        DELIVERED = "delivered", "تحویل‌شده"
        CANCELLED = "cancelled", "لغوشده"
        REFUNDED = "refunded", "مرجوع وجه‌شده"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "پرداخت نشده"
        PENDING = "pending", "در انتظار پرداخت"
        PAID = "paid", "موفق"
        FAILED = "failed", "ناموفق"
        REFUNDED = "refunded", "مرجوع"

    class ShippingStatus(models.TextChoices):
        PENDING = "pending", "در انتظار ارسال"
        PREPARING = "preparing", "در حال آماده‌سازی"
        SHIPPED = "shipped", "ارسال‌شده"
        DELIVERED = "delivered", "تحویل‌شده"
        RETURNED = "returned", "مرجوع‌شده"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    number = models.CharField(max_length=32, unique=True, db_index=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID, db_index=True)
    shipping_status = models.CharField(max_length=20, choices=ShippingStatus.choices, default=ShippingStatus.PENDING, db_index=True)

    # Immutable delivery snapshot. The order must remain correct even if the user edits/deletes the address later.
    shipping_title = models.CharField(max_length=100)
    shipping_recipient = models.CharField(max_length=200, blank=True)
    shipping_phone = models.CharField(max_length=20)
    shipping_province = models.CharField(max_length=120)
    shipping_city = models.CharField(max_length=120)
    shipping_postal_code = models.CharField(max_length=10)
    shipping_address = models.TextField()

    subtotal = models.PositiveBigIntegerField(default=0, validators=[MinValueValidator(0)])
    discount_amount = models.PositiveBigIntegerField(default=0, validators=[MinValueValidator(0)])
    shipping_amount = models.PositiveBigIntegerField(default=0, validators=[MinValueValidator(0)])
    total_amount = models.PositiveBigIntegerField(default=0, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default="IRT")

    payment_reference = models.CharField(max_length=120, blank=True, db_index=True)
    customer_note = models.TextField(blank=True)
    admin_note = models.TextField(blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("user", "-created_at")),
            models.Index(fields=("status", "-created_at")),
            models.Index(fields=("payment_status", "-created_at")),
        ]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = f"BA-{uuid.uuid4().hex[:12].upper()}"
        if self.total_amount == 0:
            self.total_amount = self.subtotal - self.discount_amount + self.shipping_amount
        super().save(*args, **kwargs)

    def __str__(self):
        return self.number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("shop.Product", on_delete=models.PROTECT, related_name="order_items")
    vendor_listing = models.ForeignKey("marketplace.VendorProduct", on_delete=models.PROTECT, related_name="order_items", null=True, blank=True)
    variant = models.ForeignKey(
        "shop.ProductVariant",
        on_delete=models.PROTECT,
        related_name="order_items",
        null=True,
        blank=True,
    )
    custom_design = models.ForeignKey(
        "customizer.DesignDraft",
        on_delete=models.PROTECT,
        related_name="order_items",
        null=True,
        blank=True,
    )
    custom_design_code = models.CharField(max_length=40, blank=True, db_index=True)
    custom_design_snapshot = models.JSONField(default=dict, blank=True)

    # Product information is intentionally snapshotted for historical accuracy.
    product_name = models.CharField(max_length=200)
    variant_sku = models.CharField(max_length=80, blank=True)
    color_name = models.CharField(max_length=80, blank=True)
    size_name = models.CharField(max_length=40, blank=True)
    unit_price = models.PositiveBigIntegerField(validators=[MinValueValidator(0)])
    compare_at_price = models.PositiveBigIntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    line_total = models.PositiveBigIntegerField(validators=[MinValueValidator(0)])

    class Meta:
        ordering = ("id",)
        constraints = [models.CheckConstraint(check=Q(quantity__gt=0), name="order_item_quantity_gt_zero")]
        indexes = [models.Index(fields=("order", "product"))]

    def save(self, *args, **kwargs):
        if not self.line_total:
            self.line_total = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order.number} / {self.product_name} × {self.quantity}"
