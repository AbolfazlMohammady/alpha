import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0011_vendor_commission_constraint"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vendor",
            name="settlement_hold_hours",
            field=models.PositiveSmallIntegerField(
                default=24,
                help_text="حداقل فاصله تحویل تا واجد شرایط شدن برای تسویه؛ کمتر از ۲۴ ساعت مجاز نیست.",
                validators=[django.core.validators.MinValueValidator(24)],
            ),
        ),
        migrations.AddConstraint(
            model_name="vendor",
            constraint=models.CheckConstraint(check=models.Q(("settlement_hold_hours__gte", 24)), name="vendor_settlement_hold_gte_24h"),
        ),
    ]
