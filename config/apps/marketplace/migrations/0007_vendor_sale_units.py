import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0006_vendor_product_submission"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendorproduct",
            name="sale_unit",
            field=models.CharField(default="عدد", help_text="واحد قابل سفارش؛ مثل عدد یا جعبه ۱۲تایی.", max_length=40),
        ),
        migrations.AddField(
            model_name="vendorproduct",
            name="units_per_order",
            field=models.PositiveIntegerField(default=1, help_text="تعداد اقلام فیزیکی در هر واحد فروش.", validators=[django.core.validators.MinValueValidator(1)]),
        ),
        migrations.AddConstraint(
            model_name="vendorproduct",
            constraint=models.CheckConstraint(check=models.Q(("units_per_order__gt", 0)), name="vendor_listing_units_per_order_gt_zero"),
        ),
        migrations.AddField(
            model_name="vendorproductsubmission",
            name="sale_unit",
            field=models.CharField(default="عدد", max_length=40),
        ),
        migrations.AddField(
            model_name="vendorproductsubmission",
            name="units_per_order",
            field=models.PositiveIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1)]),
        ),
        migrations.AddConstraint(
            model_name="vendorproductsubmission",
            constraint=models.CheckConstraint(check=models.Q(("retail_price__gt", 0)), name="vendor_submission_price_gt_zero"),
        ),
        migrations.AddConstraint(
            model_name="vendorproductsubmission",
            constraint=models.CheckConstraint(check=models.Q(("compare_at_price__isnull", True), ("compare_at_price__gte", 0), _connector="OR"), name="vendor_submission_compare_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="vendorproductsubmission",
            constraint=models.CheckConstraint(check=models.Q(("units_per_order__gt", 0)), name="vendor_submission_units_gt_zero"),
        ),
    ]
