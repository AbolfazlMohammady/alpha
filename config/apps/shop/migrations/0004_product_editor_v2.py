from django.db import migrations, models
import django.db.models.deletion


def mark_existing_variants_as_custom_price(apps, schema_editor):
    ProductVariant = apps.get_model("shop", "ProductVariant")
    ProductVariant.objects.all().update(use_product_price=False)


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0003_product_discount_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcolor",
            name="product",
            field=models.ForeignKey(
                blank=True,
                help_text="خالی باشد یعنی رنگ قدیمی/عمومی؛ رنگ‌های جدید را برای هر محصول جدا بسازید.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="colors",
                to="shop.product",
                verbose_name="محصول",
            ),
        ),
        migrations.AlterField(
            model_name="productcolor",
            name="slug",
            field=models.SlugField(allow_unicode=True, max_length=100, verbose_name="اسلاگ"),
        ),
        migrations.AddConstraint(
            model_name="productcolor",
            constraint=models.UniqueConstraint(
                fields=("product", "slug"),
                name="unique_product_color_slug",
            ),
        ),
        migrations.AddField(
            model_name="productvariant",
            name="use_product_price",
            field=models.BooleanField(
                default=True,
                help_text="اگر فعال باشد قیمت و تخفیف این تنوع از خود محصول گرفته می‌شود.",
                verbose_name="استفاده از قیمت محصول",
            ),
        ),
        migrations.RunPython(
            mark_existing_variants_as_custom_price,
            migrations.RunPython.noop,
        ),
    ]
