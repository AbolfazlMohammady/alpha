import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0002_catalog_integrity"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="compare_at_price",
            field=models.PositiveBigIntegerField(
                blank=True,
                help_text="اگر محصول تخفیف دارد، قیمت قبل از تخفیف را وارد کنید.",
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name="قیمت قبل از تخفیف",
            ),
        ),
        migrations.AddField(
            model_name="productvariant",
            name="compare_at_price",
            field=models.PositiveBigIntegerField(
                blank=True,
                help_text="در صورت تخفیف این ترکیب، قیمت قبل از تخفیف را وارد کنید.",
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name="قیمت قبل از تخفیف",
            ),
        ),
    ]
