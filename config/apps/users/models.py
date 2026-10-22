import uuid
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField


POSTAL_CODE_VALIDATOR = RegexValidator(
    regex=r"^\d{10}$",
    message=_("کد پستی باید دقیقاً ۱۰ رقم باشد."),
)


def user_profile_image_path(instance, filename):
    extension = Path(filename).suffix.lower() or ".webp"
    return f"users/{instance.uuid}/profile/{uuid.uuid4().hex}{extension}"


class RoleUser(models.TextChoices):
    CUSTOMER = "customer", _("مشتری")
    ADMIN = "admin", _("مدیر")
    STORE_MANAGER = "store_manager", _("مدیر فروشگاه")
    ORDER_MANAGER = "order_manager", _("مسئول سفارش‌ها")
    DESIGN_MANAGER = "design_manager", _("مسئول طراحی")
    SUPPORT_MANAGER = "support_manager", _("پشتیبانی")
    BLOG_MANAGER = "blog_manager", _("مدیر بلاگ")


class RoleUserGender(models.TextChoices):
    MALE = "male", _("آقا")
    FEMALE = "female", _("خانم")


class CustomUserManager(BaseUserManager):
    use_in_migrations = True

    @staticmethod
    def normalize_phone(phone):
        field = PhoneNumberField(region="IR")
        value = field.to_python(phone)
        if not value or not value.is_valid():
            raise ValueError(_("شماره تلفن معتبر نیست."))
        return value

    def create_user(self, phone, password=None, **extra_fields):
        phone = self.normalize_phone(phone)
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", RoleUser.ADMIN)
        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))
        return self.create_user(phone=phone, password=password, **extra_fields)


class User(AbstractUser):
    username = None
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    phone = PhoneNumberField(_("شماره تلفن"), region="IR", unique=True)
    email = models.EmailField(_("ایمیل"), unique=True, blank=True, null=True)
    first_name = models.CharField(_("نام"), max_length=100, blank=True)
    last_name = models.CharField(_("نام خانوادگی"), max_length=100, blank=True)
    birth_date = models.DateField(_("تاریخ تولد"), blank=True, null=True)
    role = models.CharField(_("نقش"), max_length=20, choices=RoleUser.choices, default=RoleUser.CUSTOMER)
    image = models.ImageField(_("تصویر پروفایل"), upload_to=user_profile_image_path, blank=True, null=True)
    gender = models.CharField(_("جنسیت"), max_length=10, choices=RoleUserGender.choices, blank=True, null=True)

    objects = CustomUserManager()
    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    @property
    def age(self):
        if not self.birth_date:
            return None
        today = timezone.localdate()
        age = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            age -= 1
        return age

    def __str__(self):
        return str(self.phone)


class Province(models.Model):
    name = models.CharField(_("استان"), max_length=100, unique=True)

    def __str__(self):
        return self.name


class City(models.Model):
    province = models.ForeignKey(Province, on_delete=models.CASCADE, related_name="cities", verbose_name=_("استان"))
    name = models.CharField(_("شهر"), max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["province", "name"], name="unique_city_per_province")
        ]

    def __str__(self):
        return self.name


class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses", verbose_name=_("کاربر"))
    title = models.CharField(_("عنوان"), max_length=100)
    phone = PhoneNumberField(_("شماره موبایل"), region="IR", max_length=128)
    is_for_other = models.BooleanField(
        _("این آدرس برای شخص دیگری است"),
        default=False,
        help_text=_("اگر این گزینه فعال باشد، نام تحویل‌گیرنده را وارد کنید."),
    )
    recipient_name = models.CharField(
        _("نام تحویل‌گیرنده"),
        max_length=200,
        blank=True,
        default="",
    )
    description = models.TextField(_("آدرس"), blank=True)
    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name="addresses", verbose_name=_("شهر"))
    postal_code = models.CharField(_("کد پستی"), max_length=10, validators=[POSTAL_CODE_VALIDATOR])
    is_default = models.BooleanField(_("آدرس پیش‌فرض"), default=False)

    def clean(self):
        super().clean()
        self.recipient_name = " ".join((self.recipient_name or "").split())
        if self.is_for_other and len(self.recipient_name) < 2:
            raise ValidationError(_("برای آدرس شخص دیگر، نام تحویل‌گیرنده الزامی است."))
        if not self.is_for_other:
            self.recipient_name = ""

    @property
    def recipient_display_name(self):
        if self.is_for_other and self.recipient_name:
            return self.recipient_name
        return self.user.get_full_name().strip()

    class Meta:
        ordering = ("-is_default", "-id")
        indexes = [
            models.Index(
                fields=("user", "-is_default", "-id"),
                name="users_address_account_list_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("user",),
                condition=Q(is_default=True),
                name="unique_default_address_per_user",
            ),
        ]

    def __str__(self):
        return self.title


class OTP(models.Model):
    code = models.CharField(_("کد"), max_length=128)
    phone = PhoneNumberField(_("شماره تلفن"), region="IR", max_length=128)
    created_at = models.DateTimeField(_("زمان ایجاد"), auto_now_add=True)
    expire_at = models.DateTimeField(_("زمان انقضا"))
    is_used = models.BooleanField(_("استفاده شده"), default=False)
    attempts = models.PositiveSmallIntegerField(_("تعداد تلاش"), default=0)

    class Meta:
        indexes = [models.Index(fields=("phone", "is_used", "expire_at"))]
        ordering = ("-created_at",)

    def save(self, *args, **kwargs):
        if not self.expire_at:
            self.expire_at = timezone.now() + timedelta(minutes=2)
        super().save(*args, **kwargs)

    def is_valid(self):
        return (
            self.expire_at > timezone.now()
            and not self.is_used
            and self.attempts < 5
        )

    def __str__(self):
        return f"OTP for {self.phone} ({self.created_at.isoformat()})"
