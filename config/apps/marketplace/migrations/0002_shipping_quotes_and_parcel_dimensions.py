from datetime import timedelta
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0001_initial"),
        ("orders", "0002_marketplace_vendor_listings"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="vendor",
            name="pickup_postal_code",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="vendor",
            name="pickup_address",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="vendor",
            name="pickup_city",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="vendor",
            name="pickup_province",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="vendor",
            name="contact_phone",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="vendorproduct",
            name="weight_grams",
            field=models.PositiveIntegerField(default=0, help_text="وزن بسته‌بندی‌شده بر حسب گرم؛ برای استعلام حمل الزامی است."),
        ),
        migrations.AddField(
            model_name="vendorproduct",
            name="package_length_cm",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="vendorproduct",
            name="package_width_cm",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="vendorproduct",
            name="package_height_cm",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="ShippingQuote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uuid", models.UUIDField(default=__import__("uuid").uuid4, editable=False, unique=True)),
                ("provider", models.CharField(choices=[("tipax", "تیپاکس"), ("post", "شرکت ملی پست")], max_length=16)),
                ("status", models.CharField(choices=[("valid", "معتبر"), ("consumed", "استفاده‌شده"), ("expired", "منقضی‌شده")], db_index=True, default="valid", max_length=12)),
                ("amount", models.PositiveBigIntegerField()),
                ("currency", models.CharField(default="IRT", max_length=3)),
                ("quote_reference", models.CharField(blank=True, max_length=160)),
                ("quantity", models.PositiveIntegerField()),
                ("address_fingerprint", models.CharField(db_index=True, max_length=64)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("provider_payload", models.JSONField(blank=True, default=dict)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cart_item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="shipping_quotes", to="orders.cartitem")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="marketplace_shipping_quotes", to=settings.AUTH_USER_MODEL)),
                ("vendor_listing", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="shipping_quotes", to="marketplace.vendorproduct")),
            ],
            options={"ordering": ("-created_at",), "indexes": [models.Index(fields=["user", "status", "expires_at"], name="market_quote_user_status_idx")]},
        ),
    ]
