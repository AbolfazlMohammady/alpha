# Generated for the Babaei shop catalog.
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uuid", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("name", models.CharField(max_length=120, verbose_name="نام")),
                ("slug", models.SlugField(allow_unicode=True, max_length=150, unique=True, verbose_name="اسلاگ")),
                ("description", models.TextField(blank=True, verbose_name="توضیحات")),
                ("image", models.ImageField(blank=True, null=True, upload_to="shop/categories/%Y/%m/", verbose_name="تصویر")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="فعال")),
                ("sort_order", models.PositiveIntegerField(default=0, verbose_name="ترتیب")),
                ("seo_title", models.CharField(blank=True, max_length=70, verbose_name="عنوان سئو")),
                ("seo_description", models.CharField(blank=True, max_length=160, verbose_name="توضیحات سئو")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="زمان ایجاد")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین بروزرسانی")),
            ],
            options={"ordering": ("sort_order", "name")},
        ),
        migrations.CreateModel(
            name="ProductColor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, verbose_name="نام")),
                ("slug", models.SlugField(allow_unicode=True, max_length=100, unique=True, verbose_name="اسلاگ")),
                ("hex_code", models.CharField(blank=True, max_length=7, verbose_name="کد رنگ")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="فعال")),
            ],
            options={"ordering": ("name",)},
        ),
        migrations.CreateModel(
            name="ProductSize",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=40, verbose_name="نام")),
                ("slug", models.SlugField(allow_unicode=True, max_length=60, unique=True, verbose_name="اسلاگ")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="ترتیب")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="فعال")),
            ],
            options={"ordering": ("sort_order", "name")},
        ),
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uuid", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("name", models.CharField(max_length=200, verbose_name="نام")),
                ("slug", models.SlugField(allow_unicode=True, max_length=230, unique=True, verbose_name="اسلاگ")),
                ("short_description", models.TextField(blank=True, verbose_name="توضیحات کوتاه")),
                ("description", models.TextField(blank=True, verbose_name="توضیحات کامل")),
                ("base_price", models.PositiveBigIntegerField(validators=[django.core.validators.MinValueValidator(0)], verbose_name="قیمت پایه")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="فعال")),
                ("is_featured", models.BooleanField(db_index=True, default=False, verbose_name="ویژه")),
                ("seo_title", models.CharField(blank=True, max_length=70, verbose_name="عنوان سئو")),
                ("seo_description", models.CharField(blank=True, max_length=160, verbose_name="توضیحات سئو")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="زمان ایجاد")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین بروزرسانی")),
                ("category", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="products", to="shop.category", verbose_name="دسته‌بندی")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="ProductImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(max_length=500, upload_to="shop/products/%Y/%m/", verbose_name="تصویر")),
                ("alt_text", models.CharField(blank=True, max_length=180, verbose_name="متن جایگزین")),
                ("image_type", models.CharField(choices=[("primary", "اصلی"), ("detail", "جزئیات"), ("gallery", "گالری")], default="gallery", max_length=20, verbose_name="نوع تصویر")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="ترتیب")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="images", to="shop.product", verbose_name="محصول")),
            ],
            options={"ordering": ("sort_order", "id")},
        ),
        migrations.CreateModel(
            name="ProductVariant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sku", models.CharField(max_length=80, unique=True, verbose_name="SKU")),
                ("price", models.PositiveBigIntegerField(validators=[django.core.validators.MinValueValidator(0)], verbose_name="قیمت")),
                ("stock_quantity", models.PositiveIntegerField(default=0, verbose_name="موجودی")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="فعال")),
                ("color", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="variants", to="shop.productcolor", verbose_name="رنگ")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="variants", to="shop.product", verbose_name="محصول")),
                ("size", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="variants", to="shop.productsize", verbose_name="سایز")),
            ],
            options={"ordering": ("product", "color", "size")},
        ),
        migrations.AddConstraint(
            model_name="productvariant",
            constraint=models.UniqueConstraint(fields=("product", "color", "size"), name="unique_product_variant"),
        ),
        migrations.AddIndex(model_name="category", index=models.Index(fields=("is_active", "sort_order"), name="shop_catego_is_acti_idx")),
        migrations.AddIndex(model_name="product", index=models.Index(fields=("category", "is_active", "-created_at"), name="shop_produc_catego_idx")),
        migrations.AddIndex(model_name="product", index=models.Index(fields=("is_active", "is_featured", "-created_at"), name="shop_produc_active_idx")),
        migrations.AddIndex(model_name="productimage", index=models.Index(fields=("product", "image_type", "sort_order"), name="shop_image_product_idx")),
        migrations.AddIndex(model_name="productvariant", index=models.Index(fields=("product", "is_active"), name="shop_var_product_idx")),
    ]
