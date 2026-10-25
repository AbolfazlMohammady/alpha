from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0008_unique_payout_reference"),
    ]

    operations = [
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
