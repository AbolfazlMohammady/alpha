from django.db import migrations, models
from django.db.models import Q
import apps.shop.models


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0002_rename_shop_catego_is_acti_idx_shop_catego_is_acti_b15761_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="category",
            name="image",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to=apps.shop.models.category_image_path,
                verbose_name="تصویر",
            ),
        ),
        migrations.AlterField(
            model_name="productimage",
            name="image",
            field=models.ImageField(
                max_length=500,
                upload_to=apps.shop.models.product_image_path,
                verbose_name="تصویر",
            ),
        ),
        migrations.AlterField(
            model_name="productcolor",
            name="hex_code",
            field=models.CharField(
                max_length=7,
                validators=[apps.shop.models.HEX_COLOR_VALIDATOR],
                verbose_name="کد رنگ",
            ),
        ),
        migrations.AlterModelOptions(
            name="productvariant",
            options={"ordering": ("color", "size")},
        ),
        migrations.AddConstraint(
            model_name="productimage",
            constraint=models.UniqueConstraint(
                fields=("product",),
                condition=Q(image_type="primary"),
                name="unique_primary_image_per_product",
            ),
        ),
        migrations.RemoveIndex(
            model_name="productvariant",
            name="shop_produc_product_27d2af_idx",
        ),
        migrations.AddIndex(
            model_name="productvariant",
            index=models.Index(
                fields=("product", "is_active", "color", "size"),
                name="shop_variant_lookup_idx",
            ),
        ),
    ]
