from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0010_compare_price_constraints"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="vendor",
            constraint=models.CheckConstraint(check=models.Q(("commission_bps__lte", 10000)), name="vendor_commission_bps_lte_10000"),
        ),
    ]
