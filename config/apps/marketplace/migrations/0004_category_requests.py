import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0003_financial_reconciliation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CategoryRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("pending", "در انتظار بررسی"), ("approved", "تأییدشده"), ("rejected", "ردشده")], db_index=True, default="pending", max_length=12)),
                ("reviewer_note", models.TextField(blank=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reviewed_marketplace_category_requests", to=settings.AUTH_USER_MODEL)),
                ("vendor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="category_requests", to="marketplace.vendor")),
            ],
            options={"ordering": ("-created_at",), "indexes": [models.Index(fields=["status", "created_at"], name="market_category_request_idx")]},
        ),
    ]
