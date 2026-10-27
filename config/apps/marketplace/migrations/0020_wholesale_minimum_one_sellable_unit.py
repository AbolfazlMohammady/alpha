from django.db import migrations, models
import django.core.validators
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0019_vendor_sale_modes"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="wholesalepricetier",
            name="wholesale_min_qty_gte_two",
        ),
        migrations.AddConstraint(
            model_name="wholesalepricetier",
            constraint=models.CheckConstraint(
                check=Q(minimum_quantity__gte=1),
                name="wholesale_min_qty_gte_one",
            ),
        ),
        migrations.AlterField(
            model_name="wholesalepricetier",
            name="minimum_quantity",
            field=models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)]),
        ),
        migrations.AlterField(
            model_name="vendorproductsubmission",
            name="wholesale_minimum_quantity",
            field=models.PositiveIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1)]),
        ),
    ]
