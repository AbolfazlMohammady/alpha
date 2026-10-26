import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0013_journal_line_constraint_state"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VendorApplication",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contact_name", models.CharField(max_length=200)),
                ("contact_email", models.EmailField(blank=True, max_length=254)),
                ("contact_phone", models.CharField(max_length=20)),
                ("national_id", models.CharField(help_text="اطلاعات هویتی محرمانه؛ فقط مدیر مجاز به مشاهده باشد.", max_length=10)),
                ("store_name", models.CharField(max_length=160)),
                ("seller_type", models.CharField(choices=[("retail", "خرده‌فروشی"), ("wholesale", "عمده‌فروشی"), ("both", "خرده‌فروشی و عمده‌فروشی")], max_length=12)),
                ("province", models.CharField(blank=True, max_length=120)),
                ("city", models.CharField(blank=True, max_length=120)),
                ("postal_code", models.CharField(blank=True, max_length=10)),
                ("address", models.TextField(blank=True)),
                ("website_or_social", models.URLField(blank=True, max_length=500)),
                ("description", models.TextField()),
                ("status", models.CharField(choices=[("pending", "در انتظار بررسی"), ("approved", "تأییدشده"), ("rejected", "ردشده")], db_index=True, default="pending", max_length=12)),
                ("reviewer_note", models.TextField(blank=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reviewed_vendor_applications", to=settings.AUTH_USER_MODEL)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="vendor_application", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("status", "-created_at"),
                "indexes": [models.Index(fields=["status", "created_at"], name="market_vapp_status_idx")],
            },
        ),
    ]
