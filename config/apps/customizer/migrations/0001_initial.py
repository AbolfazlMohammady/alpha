import uuid

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import apps.customizer.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("shop", "0003_product_discount_fields"),
    ]

    operations = [
        migrations.CreateModel(name="Artwork", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("uuid", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("name", models.CharField(max_length=160, verbose_name="نام لیبل")),
            ("slug", models.SlugField(allow_unicode=True, max_length=190, unique=True, verbose_name="اسلاگ")),
            ("image", models.ImageField(upload_to=apps.customizer.models._asset_path, validators=[django.core.validators.FileExtensionValidator(["jpg", "jpeg", "png", "webp"])], verbose_name="لیبل آماده")),
            ("original_image", models.ImageField(blank=True, null=True, upload_to=apps.customizer.models._original_asset_path, validators=[django.core.validators.FileExtensionValidator(["jpg", "jpeg", "png", "webp"])], verbose_name="تصویر اصلی")),
            ("source", models.CharField(choices=[("library", "کتابخانه"), ("upload", "آپلود مشتری")], default="library", max_length=20, verbose_name="منبع")),
            ("processing_status", models.CharField(choices=[("ready", "آماده"), ("processing", "در حال پردازش"), ("failed", "ناموفق")], default="ready", max_length=20, verbose_name="وضعیت پردازش")),
            ("background_removed", models.BooleanField(default=True, verbose_name="پس‌زمینه حذف شده")),
            ("base_price", models.PositiveBigIntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)], verbose_name="قیمت پایه لیبل")),
            ("min_width_px", models.PositiveIntegerField(default=500, verbose_name="حداقل عرض فایل")),
            ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="فعال")),
            ("session_key", models.CharField(blank=True, db_index=True, max_length=64, verbose_name="کلید نشست")),
            ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="زمان ایجاد")),
            ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین بروزرسانی")),
            ("owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="customizer_artworks", to=settings.AUTH_USER_MODEL, verbose_name="مالک")),
        ], options={"ordering": ("-created_at",), "indexes": [models.Index(fields=("is_active", "source", "-created_at"), name="customizer_artwork_active_idx")]}),
        migrations.CreateModel(name="DesignerView", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("key", models.SlugField(allow_unicode=True, max_length=60, verbose_name="کلید نما")),
            ("name", models.CharField(max_length=80, verbose_name="نام نما")),
            ("background_image", models.ImageField(upload_to=apps.customizer.models._view_image_path, verbose_name="تصویر لباس")),
            ("mask_image", models.ImageField(blank=True, null=True, upload_to=apps.customizer.models._mask_image_path, verbose_name="ماسک و سایه")),
            ("canvas_width", models.PositiveIntegerField(default=1600, verbose_name="عرض مرجع")),
            ("canvas_height", models.PositiveIntegerField(default=1600, verbose_name="ارتفاع مرجع")),
            ("angle", models.SmallIntegerField(default=0, validators=[django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)], verbose_name="زاویه")),
            ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="ترتیب")),
            ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="فعال")),
            ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="designer_views", to="shop.product", verbose_name="محصول")),
        ], options={"ordering": ("sort_order", "id"), "indexes": [models.Index(fields=("product", "is_active", "sort_order"), name="customizer_view_lookup_idx")], "constraints": [models.UniqueConstraint(fields=("product", "key"), name="unique_designer_view_per_product")] }),
        migrations.CreateModel(name="PrintArea", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("key", models.SlugField(allow_unicode=True, max_length=70, verbose_name="کلید ناحیه")),
            ("name", models.CharField(max_length=100, verbose_name="نام ناحیه")),
            ("max_width_mm", models.DecimalField(decimal_places=2, default=100, max_digits=7, verbose_name="حداکثر عرض چاپ (mm)")),
            ("max_height_mm", models.DecimalField(decimal_places=2, default=100, max_digits=7, verbose_name="حداکثر ارتفاع چاپ (mm)")),
            ("max_layers", models.PositiveSmallIntegerField(default=3, verbose_name="حداکثر تعداد لیبل")),
            ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="ترتیب")),
            ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="فعال")),
            ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="print_areas", to="shop.product", verbose_name="محصول")),
        ], options={"ordering": ("sort_order", "id"), "indexes": [models.Index(fields=("product", "is_active", "sort_order"), name="customizer_area_lookup_idx")], "constraints": [models.UniqueConstraint(fields=("product", "key"), name="unique_print_area_per_product")] }),
        migrations.CreateModel(name="DesignDraft", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("uuid", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("session_key", models.CharField(blank=True, db_index=True, max_length=64)),
            ("status", models.CharField(choices=[("draft", "پیش‌نویس"), ("confirmed", "تأییدشده"), ("expired", "منقضی")], db_index=True, default="draft", max_length=20)),
            ("total_price", models.PositiveBigIntegerField(default=0)),
            ("payload", models.JSONField(blank=True, default=dict)),
            ("preview_image", models.ImageField(blank=True, null=True, upload_to="customizer/previews/%Y/%m/")),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="design_drafts", to="shop.product")),
            ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="design_drafts", to=settings.AUTH_USER_MODEL)),
            ("variant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="design_drafts", to="shop.productvariant")),
        ], options={"ordering": ("-updated_at",), "indexes": [models.Index(fields=("product", "status", "-updated_at"), name="customizer_draft_lookup_idx")] }),
        migrations.CreateModel(name="PrintAreaView", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("geometry", models.JSONField(validators=[apps.customizer.models._validate_geometry], verbose_name="چندضلعی ناحیه")),
            ("area", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="view_maps", to="customizer.printarea", verbose_name="ناحیه چاپ")),
            ("view", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="area_maps", to="customizer.designerview", verbose_name="نما")),
        ], options={"constraints": [models.UniqueConstraint(fields=("area", "view"), name="unique_print_area_view")] }),
        migrations.CreateModel(name="ArtworkAreaPrice", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("price", models.PositiveBigIntegerField(validators=[django.core.validators.MinValueValidator(0)], verbose_name="قیمت")),
            ("area", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="artwork_prices", to="customizer.printarea", verbose_name="ناحیه چاپ")),
            ("artwork", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="area_prices", to="customizer.artwork", verbose_name="لیبل")),
        ], options={"indexes": [models.Index(fields=("area", "artwork"), name="customizer_price_lookup_idx")], "constraints": [models.UniqueConstraint(fields=("artwork", "area"), name="unique_artwork_area_price")] }),
        migrations.CreateModel(name="DesignLayer", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("x", models.FloatField(validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(1)], verbose_name="مرکز X")),
            ("y", models.FloatField(validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(1)], verbose_name="مرکز Y")),
            ("width", models.FloatField(validators=[django.core.validators.MinValueValidator(0.01), django.core.validators.MaxValueValidator(1)], verbose_name="عرض")),
            ("height", models.FloatField(validators=[django.core.validators.MinValueValidator(0.01), django.core.validators.MaxValueValidator(1)], verbose_name="ارتفاع")),
            ("rotation", models.FloatField(default=0, validators=[django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)], verbose_name="چرخش")),
            ("z_index", models.PositiveSmallIntegerField(default=0, verbose_name="ترتیب لایه")),
            ("area", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="design_layers", to="customizer.printarea")),
            ("artwork", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="design_layers", to="customizer.artwork")),
            ("draft", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="layers", to="customizer.designdraft")),
        ], options={"ordering": ("z_index", "id"), "indexes": [models.Index(fields=("draft", "area", "z_index"), name="customizer_layer_lookup_idx")] }),
    ]
