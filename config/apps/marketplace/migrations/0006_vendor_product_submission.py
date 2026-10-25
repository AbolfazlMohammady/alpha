import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0005_settlement_payout_attempts"),
        ("shop", "0003_product_discount_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VendorProductSubmission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("short_description", models.TextField(blank=True)),
                ("description", models.TextField(blank=True)),
                ("image", models.ImageField(upload_to="marketplace/product-submissions/")),
                ("retail_price", models.PositiveBigIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("compare_at_price", models.PositiveBigIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("stock_quantity", models.PositiveIntegerField(default=0)),
                ("weight_grams", models.PositiveIntegerField(default=0)),
                ("package_length_cm", models.PositiveSmallIntegerField(default=0)),
                ("package_width_cm", models.PositiveSmallIntegerField(default=0)),
                ("package_height_cm", models.PositiveSmallIntegerField(default=0)),
                ("handling_days", models.PositiveSmallIntegerField(default=2)),
                ("supports_custom_printing", models.BooleanField(default=False)),
                ("status", models.CharField(choices=[("pending", "در انتظار بررسی"), ("approved", "تأییدشده"), ("rejected", "ردشده")], db_index=True, default="pending", max_length=12)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("reviewer_note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("category", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="vendor_product_submissions", to="shop.category")),
                ("listing", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="source_submissions", to="marketplace.vendorproduct")),
                ("product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="vendor_submissions", to="shop.product")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reviewed_vendor_product_submissions", to=settings.AUTH_USER_MODEL)),
                ("vendor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="product_submissions", to="marketplace.vendor")),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [models.Index(fields=["vendor", "status", "created_at"], name="market_prod_sub_status_idx")],
            },
        ),
    ]
