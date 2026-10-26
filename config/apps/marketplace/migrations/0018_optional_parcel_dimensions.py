from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0017_vendor_seller_type"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="vendorproduct",
            name="vendor_listing_weight_gt_zero",
        ),
        migrations.RemoveConstraint(
            model_name="vendorproduct",
            name="vendor_listing_length_gt_zero",
        ),
        migrations.RemoveConstraint(
            model_name="vendorproduct",
            name="vendor_listing_width_gt_zero",
        ),
        migrations.RemoveConstraint(
            model_name="vendorproduct",
            name="vendor_listing_height_gt_zero",
        ),
        migrations.RemoveConstraint(
            model_name="vendorproductsubmission",
            name="vendor_submission_weight_gt_zero",
        ),
        migrations.RemoveConstraint(
            model_name="vendorproductsubmission",
            name="vendor_submission_length_gt_zero",
        ),
        migrations.RemoveConstraint(
            model_name="vendorproductsubmission",
            name="vendor_submission_width_gt_zero",
        ),
        migrations.RemoveConstraint(
            model_name="vendorproductsubmission",
            name="vendor_submission_height_gt_zero",
        ),
    ]
