from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0009_shipping_package_constraints"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="vendorproduct",
            name="vendor_listing_compare_nonnegative",
        ),
        migrations.AddConstraint(
            model_name="vendorproduct",
            constraint=models.CheckConstraint(
                check=models.Q(("compare_at_price__isnull", True), ("compare_at_price__gte", models.F("retail_price")), _connector="OR"),
                name="vendor_listing_compare_gte_retail",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="vendorproductsubmission",
            name="vendor_submission_compare_nonnegative",
        ),
        migrations.AddConstraint(
            model_name="vendorproductsubmission",
            constraint=models.CheckConstraint(
                check=models.Q(("compare_at_price__isnull", True), ("compare_at_price__gte", models.F("retail_price")), _connector="OR"),
                name="vendor_submission_compare_gte_retail",
            ),
        ),
    ]
