import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0002_shipping_quotes_and_parcel_dimensions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FinancialReconciliation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uuid", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("source", models.CharField(choices=[("payment_gateway", "درگاه پرداخت"), ("bank_payout", "واریز بانکی"), ("carrier_invoice", "صورتحساب حمل"), ("bank_statement", "گردش حساب بانکی"), ("manual", "ثبت دستی")], db_index=True, max_length=24)),
                ("external_reference", models.CharField(max_length=180)),
                ("internal_reference", models.CharField(blank=True, db_index=True, max_length=180)),
                ("expected_amount", models.BigIntegerField(blank=True, null=True)),
                ("actual_amount", models.BigIntegerField(blank=True, null=True)),
                ("currency", models.CharField(default="IRT", max_length=3)),
                ("status", models.CharField(choices=[("unmatched", "ناقص"), ("matched", "تطبیق‌شده"), ("mismatch", "دارای مغایرت")], db_index=True, default="unmatched", max_length=12)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("reconciled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("recorded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="marketplace_reconciliations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",), "indexes": [models.Index(fields=["source", "status", "created_at"], name="market_reconcile_status_idx")], "constraints": [models.UniqueConstraint(fields=("source", "external_reference"), name="unique_external_reconciliation_ref")]},
        ),
    ]
