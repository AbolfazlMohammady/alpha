import django.core.validators
import django.db.models.deletion
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
        migrations.RunPython(
            code=lambda apps, schema_editor: apps.get_model("marketplace", "VendorProduct").objects.filter(
                models.Q(weight_grams=0) | models.Q(package_length_cm=0) |
                models.Q(package_width_cm=0) | models.Q(package_height_cm=0)
            ).update(
                weight_grams=1, package_length_cm=1, package_width_cm=1, package_height_cm=1,
                status="paused",
            ),
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveConstraint(
            model_name="vendorproduct",
            name="vendor_listing_compare_nonnegative",
        ),
        migrations.AddConstraint(
            model_name="vendorproduct",
            constraint=models.CheckConstraint(check=models.Q(("compare_at_price__isnull", True), ("compare_at_price__gte", models.F("retail_price")), _connector="OR"), name="vendor_listing_compare_gte_retail"),
        ),
        migrations.AddConstraint(
            model_name="vendorproduct",
            constraint=models.CheckConstraint(check=models.Q(("units_per_order__gt", 0)), name="vendor_listing_units_per_order_gt_zero"),
        ),
        migrations.AddConstraint(
            model_name="vendorproduct",
            constraint=models.CheckConstraint(check=models.Q(("weight_grams__gt", 0)), name="vendor_listing_weight_gt_zero"),
        ),
        migrations.AddConstraint(
            model_name="vendorproduct",
            constraint=models.CheckConstraint(check=models.Q(("package_length_cm__gt", 0)), name="vendor_listing_length_gt_zero"),
        ),
        migrations.AddConstraint(
            model_name="vendorproduct",
            constraint=models.CheckConstraint(check=models.Q(("package_width_cm__gt", 0)), name="vendor_listing_width_gt_zero"),
        ),
        migrations.AddConstraint(
            model_name="vendorproduct",
            constraint=models.CheckConstraint(check=models.Q(("package_height_cm__gt", 0)), name="vendor_listing_height_gt_zero"),
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
            constraint=models.CheckConstraint(check=models.Q(("compare_at_price__isnull", True), ("compare_at_price__gte", models.F("retail_price")), _connector="OR"), name="vendor_submission_compare_gte_retail"),
        ),
        migrations.AddConstraint(
            model_name="vendorproductsubmission",
            constraint=models.CheckConstraint(check=models.Q(("units_per_order__gt", 0)), name="vendor_submission_units_gt_zero"),
        ),
        migrations.AddConstraint(
            model_name="vendorproductsubmission",
            constraint=models.CheckConstraint(check=models.Q(("weight_grams__gt", 0)), name="vendor_submission_weight_gt_zero"),
        ),
        migrations.AddConstraint(
            model_name="vendorproductsubmission",
            constraint=models.CheckConstraint(check=models.Q(("package_length_cm__gt", 0)), name="vendor_submission_length_gt_zero"),
        ),
        migrations.AddConstraint(
            model_name="vendorproductsubmission",
            constraint=models.CheckConstraint(check=models.Q(("package_width_cm__gt", 0)), name="vendor_submission_width_gt_zero"),
        ),
        migrations.AddConstraint(
            model_name="vendorproductsubmission",
            constraint=models.CheckConstraint(check=models.Q(("package_height_cm__gt", 0)), name="vendor_submission_height_gt_zero"),
        ),
    ]
