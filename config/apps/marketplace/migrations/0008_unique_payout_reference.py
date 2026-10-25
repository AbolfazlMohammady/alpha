from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0007_vendor_sale_units"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="settlementbatch",
            constraint=models.UniqueConstraint(
                fields=("payout_reference",),
                condition=~Q(payout_reference=""),
                name="unique_settlement_payout_reference",
            ),
        ),
    ]
