from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


HEX_COLOR_VALIDATOR = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message=_("کد رنگ باید به صورت #RRGGBB باشد."),
)


def product_image_path(instance, filename):
    extension = Path(filename).suffix.lower() or ".webp"
    return f"shop/products/{instance.product.uuid}/{uuid.uuid4().hex}{extension}"


def category_image_path(instance, filename):
    extension = Path(filename).suffix.lower() or ".webp"
    return f"shop/categories/{instance.uuid}/{uuid.uuid4().hex}{extension}"


class Category(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(_("نام"), max_length=120)
    slug = models.SlugField(_("اسلاگ"), max_length=150, unique=True, allow_unicode=True)
    description = models.TextField(_("توضیحات"), blank=True)
    image = models.ImageField(_("تصویر"), upload_to=category_image_path, blank=True, null=True)
    is_active = models.BooleanField(_("فعال"), default=True, db_index=True)
    sort_order = models.PositiveIntegerField(_("ترتیب"), default=0)
    seo_title = models.CharField(_("عنوان سئو"), max_length=70, blank=True)
    seo_description = models.CharField(_("توضیحات سئو"), max_length=160, blank=True)
    created_at = models.DateTimeField(_("زمان ایجاد"), auto_now_add=True)
    updated_at = models.DateTimeField(_("آخرین بروزرسانی"), auto_now=True)

    class Meta:
        ordering = ("sort_order", "name")
        indexes = [models.Index(fields=("is_active", "sort_order"))]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("shop:category", kwargs={"slug": self.slug})

    def __str__(self):
        return self.name


class Product(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products", verbose_name=_("دسته‌بندی"))
    name = models.CharField(_("نام"), max_length=200)
    slug = models.SlugField(_("اسلاگ"), max_length=230, unique=True, allow_unicode=True)
    short_description = models.TextField(_("توضیحات کوتاه"), blank=True)
    description = models.TextField(_("توضیحات کامل"), blank=True)
    base_price = models.PositiveBigIntegerField(_("قیمت پایه"), validators=[MinValueValidator(0)])
    compare_at_price = models.PositiveBigIntegerField(
        _("قیمت قبل از تخفیف"),
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text=_("اگر محصول تخفیف دارد، قیمت قبل از تخفیف را وارد کنید."),
    )
    marketplace_only = models.BooleanField(
        _("فروش فقط از طریق فروشندگان"),
        default=False,
        help_text=_("برای محصولاتی که توسط فروشنده ثبت شده‌اند و نباید بدون آگهی فعال فروشگاه خریداری شوند."),
    )
    is_active = models.BooleanField(_("فعال"), default=True, db_index=True)
    is_featured = models.BooleanField(_("ویژه"), default=False, db_index=True)
    seo_title = models.CharField(_("عنوان سئو"), max_length=70, blank=True)
    seo_description = models.CharField(_("توضیحات سئو"), max_length=160, blank=True)
    created_at = models.DateTimeField(_("زمان ایجاد"), auto_now_add=True)
    updated_at = models.DateTimeField(_("آخرین بروزرسانی"), auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("category", "is_active", "-created_at")),
            models.Index(fields=("is_active", "is_featured", "-created_at")),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("shop:product", kwargs={"slug": self.slug})

    def _prefetched_variants(self):
        # Catalog/account pages use Prefetch(..., to_attr="active_variants")
        # because a plain related-manager cache is slower and less explicit.
        variants = getattr(self, "active_variants", None)
        if variants is not None:
            return variants
        return getattr(self, "_prefetched_objects_cache", {}).get("active_variants")

    def _lowest_variant(self):
        variants = self._prefetched_variants()
        if not variants:
            return None
        return min(variants, key=lambda variant: variant.effective_price)

    @property
    def display_price(self):
        annotated_price = self.__dict__.get("listed_price")
        if annotated_price is not None:
            return annotated_price
        current = self._lowest_variant()
        return current.effective_price if current else self.base_price

    @property
    def display_compare_price(self):
        annotated_price = self.__dict__.get("listed_compare_price")
        if annotated_price is not None and annotated_price > self.display_price:
            return annotated_price
        current = self._lowest_variant()
        if current and current.has_discount:
            return current.effective_compare_at_price
        if self.compare_at_price and self.compare_at_price > self.display_price:
            return self.compare_at_price
        return None

    @property
    def has_discount(self):
        return self.display_compare_price is not None

    @property
    def discount_percent(self):
        compare_price = self.display_compare_price
        if not compare_price:
            return 0
        return round((compare_price - self.display_price) * 100 / compare_price)

    @property
    def total_stock(self):
        variants = self._prefetched_variants()
        if variants is None:
            return None
        return sum(variant.stock_quantity for variant in variants)

    def __str__(self):
        return self.name


class ProductColor(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="colors",
        null=True,
        blank=True,
        verbose_name=_("محصول"),
        help_text=_("خالی باشد یعنی رنگ قدیمی/عمومی؛ رنگ‌های جدید را برای هر محصول جدا بسازید."),
    )
    name = models.CharField(_("نام"), max_length=80)
    slug = models.SlugField(_("اسلاگ"), max_length=100, allow_unicode=True)
    hex_code = models.CharField(_("کد رنگ"), max_length=7, validators=[HEX_COLOR_VALIDATOR])
    is_active = models.BooleanField(_("فعال"), default=True, db_index=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=("product", "slug"), name="unique_product_color_slug"),
        ]

    def __str__(self):
        return self.name


class ProductSize(models.Model):
    name = models.CharField(_("نام"), max_length=40)
    slug = models.SlugField(_("اسلاگ"), max_length=60, allow_unicode=True)
    sort_order = models.PositiveSmallIntegerField(_("ترتیب"), default=0)
    is_active = models.BooleanField(_("فعال"), default=True, db_index=True)

    class Meta:
        ordering = ("sort_order", "name")
        constraints = [models.UniqueConstraint(fields=("slug",), name="unique_product_size_slug")]

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants", verbose_name=_("محصول"))
    color = models.ForeignKey(ProductColor, on_delete=models.PROTECT, related_name="variants", verbose_name=_("رنگ"))
    size = models.ForeignKey(ProductSize, on_delete=models.PROTECT, related_name="variants", verbose_name=_("سایز"))
    sku = models.CharField(_("SKU"), max_length=80, unique=True)
    use_product_price = models.BooleanField(
        _("استفاده از قیمت محصول"),
        default=True,
        help_text=_("اگر فعال باشد قیمت و تخفیف این تنوع از خود محصول گرفته می‌شود."),
    )
    price = models.PositiveBigIntegerField(_("قیمت"), validators=[MinValueValidator(0)])
    compare_at_price = models.PositiveBigIntegerField(
        _("قیمت قبل از تخفیف"),
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text=_("در صورت تخفیف این ترکیب، قیمت قبل از تخفیف را وارد کنید."),
    )
    stock_quantity = models.PositiveIntegerField(_("موجودی"), default=0)
    is_active = models.BooleanField(_("فعال"), default=True, db_index=True)

    class Meta:
        ordering = ("color", "size")
        constraints = [
            models.UniqueConstraint(fields=("product", "color", "size"), name="unique_product_variant"),
        ]
        indexes = [models.Index(fields=("product", "is_active", "color", "size"), name="shop_variant_lookup_idx")]

    @property
    def effective_price(self):
        return self.product.base_price if self.use_product_price else self.price

    @property
    def effective_compare_at_price(self):
        if self.use_product_price:
            return self.product.compare_at_price
        return self.compare_at_price

    @property
    def in_stock(self):
        return self.stock_quantity > 0

    @property
    def has_discount(self):
        compare = self.effective_compare_at_price
        return bool(compare and compare > self.effective_price)

    @property
    def discount_percent(self):
        compare = self.effective_compare_at_price
        price = self.effective_price
        if not compare or compare <= price:
            return 0
        return round((compare - price) * 100 / compare)

    def __str__(self):
        return f"{self.product} / {self.color} / {self.size}"


class ProductImage(models.Model):
    class ImageType(models.TextChoices):
        PRIMARY = "primary", _("اصلی")
        DETAIL = "detail", _("جزئیات")
        GALLERY = "gallery", _("گالری")

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images", verbose_name=_("محصول"))
    image = models.ImageField(_("تصویر"), upload_to=product_image_path, max_length=500)
    alt_text = models.CharField(_("متن جایگزین"), max_length=180, blank=True)
    image_type = models.CharField(_("نوع تصویر"), max_length=20, choices=ImageType.choices, default=ImageType.GALLERY)
    sort_order = models.PositiveSmallIntegerField(_("ترتیب"), default=0)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("product",),
                condition=Q(image_type="primary"),
                name="unique_primary_image_per_product",
            ),
        ]
        indexes = [models.Index(fields=("product", "image_type", "sort_order"))]

    def __str__(self):
        return f"{self.product} - {self.image_type}"


class ProductComment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("در انتظار بررسی")
        APPROVED = "approved", _("تأییدشده")
        REJECTED = "rejected", _("ردشده")

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name=_("محصول"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_comments",
        verbose_name=_("کاربر"),
    )
    body = models.TextField(_("متن نظر"), max_length=2000)
    rating = models.PositiveSmallIntegerField(
        _("امتیاز"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=_("اختیاری؛ از ۱ تا ۵ ستاره."),
    )
    status = models.CharField(
        _("وضعیت"),
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    verified_purchase = models.BooleanField(_("خرید تأییدشده"), default=False, db_index=True)
    created_at = models.DateTimeField(_("زمان ثبت"), auto_now_add=True)
    updated_at = models.DateTimeField(_("آخرین بروزرسانی"), auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(check=Q(rating__isnull=True) | Q(rating__gte=1, rating__lte=5), name="shop_comment_rating_valid"),
        ]
        indexes = [
            models.Index(fields=("product", "status", "-created_at"), name="shop_comment_product_idx"),
            models.Index(fields=("user", "status", "-created_at"), name="shop_comment_user_idx"),
        ]

    def clean(self):
        super().clean()
        if self.rating is not None and self.rating > 5:
            from django.core.exceptions import ValidationError
            raise ValidationError({"rating": _("امتیاز باید بین ۱ تا ۵ باشد.")})

    @property
    def display_name(self):
        name = f"{self.user.first_name} {self.user.last_name}".strip()
        return name or "کاربر BABAEI"

    def __str__(self):
        return f"{self.product} / {self.display_name}"


CONTACT_PAGE_CACHE_KEY = "babaei:shop:contact-page-settings:v1"


class ContactPageSettings(models.Model):
    """
    Singleton content for the public contact page.
    Editable from the Control Center; no public write access.
    """
    title = models.CharField(_("عنوان"), max_length=120, default="تماس با ما")
    intro = models.TextField(
        _("متن معرفی"),
        max_length=1000,
        default="اگر سوالی داری یا برای سفارش به راهنمایی نیاز داری، با ما در ارتباط باش.",
    )
    phone = models.CharField(_("شماره تماس"), max_length=40, default="")
    phone_label = models.CharField(_("عنوان شماره"), max_length=80, default="پشتیبانی و تماس")
    updated_at = models.DateTimeField(_("آخرین بروزرسانی"), auto_now=True)

    class Meta:
        verbose_name = _("تنظیمات صفحه تماس")
        verbose_name_plural = _("تنظیمات صفحه تماس")

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        result = super().save(*args, **kwargs)
        cache.delete(CONTACT_PAGE_CACHE_KEY)
        return result

    def __str__(self):
        return self.title
