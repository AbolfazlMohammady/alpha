import django.core.validators
from django.db import migrations, models


def backfill_legacy_shipping_data(apps, schema_editor):
    VendorProduct = apps.get_model("marketplace", "VendorProduct")
    VendorProductSubmission = apps.get_model("marketplace", "VendorProductSubmission")

    missing_listing_shipping = (
        models.Q(weight_grams=0)
        | models.Q(package_length_cm=0)
        | models.Q(package_width_cm=0)
        | models.Q(package_height_cm=0)
    )
    VendorProduct.objects.filter(missing_listing_shipping).update(
        weight_grams=models.Case(
            models.When(weight_grams=0, then=models.Value(1)),
            default=models.F("weight_grams"),
            output_field=models.PositiveIntegerField(),
        ),
        package_length_cm=models.Case(
            models.When(package_length_cm=0, then=models.Value(1)),
            default=models.F("package_length_cm"),
            output_field=models.PositiveSmallIntegerField(),
        ),
        package_width_cm=models.Case(
            models.When(package_width_cm=0, then=models.Value(1)),
            default=models.F("package_width_cm"),
            output_field=models.PositiveSmallIntegerField(),
        ),
        package_height_cm=models.Case(
            models.When(package_height_cm=0, then=models.Value(1)),
            default=models.F("package_height_cm"),
            output_field=models.PositiveSmallIntegerField(),
        ),
        status="paused",
    )
    VendorProduct.objects.filter(
        compare_at_price__isnull=False,
        compare_at_price__lt=models.F("retail_price"),
    ).update(compare_at_price=None, status="paused")

    # Legacy submissions with fabricated placeholder shipping data must not be
    # approved. Keep them rejected until the seller submits real package data.
    missing_submission_shipping = (
        models.Q(weight_grams=0)
        | models.Q(package_length_cm=0)
        | models.Q(package_width_cm=0)
        | models.Q(package_height_cm=0)
    )
    VendorProductSubmission.objects.filter(missing_submission_shipping).update(
        weight_grams=models.Case(
            models.When(weight_grams=0, then=models.Value(1)),
            default=models.F("weight_grams"),
            output_field=models.PositiveIntegerField(),
        ),
        package_length_cm=models.Case(
            models.When(package_length_cm=0, then=models.Value(1)),
            default=models.F("package_length_cm"),
            output_field=models.PositiveSmallIntegerField(),
        ),
        package_width_cm=models.Case(
            models.When(package_width_cm=0, then=models.Value(1)),
            default=models.F("package_width_cm"),
            output_field=models.PositiveSmallIntegerField(),
        ),
        package_height_cm=models.Case(
            models.When(package_height_cm=0, then=models.Value(1)),
            default=models.F("package_height_cm"),
            output_field=models.PositiveSmallIntegerField(),
        ),
        status="rejected",
        reviewer_note="درخواست قدیمی فاقد اطلاعات معتبر حمل بود؛ لطفاً با وزن و ابعاد واقعی دوباره ثبت شود.",
    )
    VendorProductSubmission.objects.filter(
        compare_at_price__isnull=False,
        compare_at_price__lt=models.F("retail_price"),
    ).update(
        compare_at_price=None,
        status="rejected",
        reviewer_note="قیمت قبل از تخفیف معتبر نبود؛ لطفاً درخواست را با قیمت اصلاح‌شده دوباره ثبت کنید.",
    )


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
        migrations.RunPython(
            code=backfill_legacy_shipping_data,
            reverse_code=migrations.RunPython.noop,
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
