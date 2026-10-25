import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0002_marketplace_vendor_listings"),
        ("marketplace", "0007_vendor_sale_units"),
    ]

    operations = [

        migrations.AddField(
            model_name="cartitem",
            name="vendor_sale_unit_snapshot",
            field=models.CharField(default="عدد", max_length=40),
        ),
        migrations.AddField(
            model_name="cartitem",
            name="vendor_units_per_order_snapshot",
            field=models.PositiveIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1)]),
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.CheckConstraint(check=models.Q(("vendor_units_per_order_snapshot__gt", 0)), name="cart_item_vendor_units_gt_zero"),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="vendor_sale_unit_snapshot",
            field=models.CharField(default="عدد", max_length=40),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="vendor_units_per_order_snapshot",
            field=models.PositiveIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1)]),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(check=models.Q(("vendor_units_per_order_snapshot__gt", 0)), name="order_item_vendor_units_gt_zero"),
        ),
    ]
