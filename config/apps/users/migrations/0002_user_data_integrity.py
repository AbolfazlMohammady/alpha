from django.db import migrations, models
from django.db.models import Q
import django.core.validators
import phonenumber_field.modelfields
import apps.users.models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="phone",
            field=phonenumber_field.modelfields.PhoneNumberField(max_length=128, region="IR", unique=True, verbose_name="شماره تلفن"),
        ),
        migrations.AlterField(
            model_name="user",
            name="image",
            field=models.ImageField(blank=True, null=True, upload_to=apps.users.models.user_profile_image_path, verbose_name="تصویر پروفایل"),
        ),
        migrations.AlterField(
            model_name="address",
            name="phone",
            field=phonenumber_field.modelfields.PhoneNumberField(max_length=128, region="IR", verbose_name="شماره موبایل"),
        ),
        migrations.AlterField(
            model_name="address",
            name="postal_code",
            field=models.CharField(
                max_length=10,
                validators=[django.core.validators.RegexValidator("^\\d{10}$", "کد پستی باید دقیقاً ۱۰ رقم باشد.")],
                verbose_name="کد پستی",
            ),
        ),
        migrations.AddField(
            model_name="address",
            name="is_default",
            field=models.BooleanField(default=False, verbose_name="آدرس پیش‌فرض"),
        ),
        migrations.AlterModelOptions(
            name="address",
            options={"ordering": ("-is_default", "-id")},
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=("user", "is_default"), name="users_address_user_default_idx"),
        ),
        migrations.AddIndex(
            model_name="otp",
            index=models.Index(fields=("phone", "is_used", "expire_at"), name="users_otp_verify_idx"),
        ),
        migrations.AlterModelOptions(
            name="otp",
            options={"ordering": ("-created_at",)},
        ),
        migrations.AlterField(
            model_name="otp",
            name="phone",
            field=phonenumber_field.modelfields.PhoneNumberField(max_length=128, region="IR", verbose_name="شماره تلفن"),
        ),
        migrations.AddConstraint(
            model_name="address",
            constraint=models.UniqueConstraint(fields=("user",), condition=Q(is_default=True), name="unique_default_address_per_user"),
        ),
    ]
