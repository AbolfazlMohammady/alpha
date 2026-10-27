from django.db import migrations, models
import django.core.validators


def backfill_sale_type(apps, schema_editor):
    VendorProduct = apps.get_model("marketplace", "VendorProduct")
    VendorProduct.objects.filter(wholesale_enabled=True).update(sale_type="both")


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0018_optional_parcel_dimensions"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendorproduct",
            name="sale_type",
            field=models.CharField(
                choices=[("retail", "فقط تکی"), ("wholesale", "فقط عمده"), ("both", "تکی و عمده")],
                default="retail",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="vendorproductsubmission",
            name="sale_type",
            field=models.CharField(
                choices=[("retail", "فقط تکی"), ("wholesale", "فقط عمده"), ("both", "تکی و عمده")],
                default="retail",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="vendorproductsubmission",
            name="wholesale_minimum_quantity",
            field=models.PositiveIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(2)]),
        ),
        migrations.AddField(
            model_name="vendorproductsubmission",
            name="wholesale_unit_price",
            field=models.PositiveBigIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1)]),
        ),
        migrations.RunPython(backfill_sale_type, migrations.RunPython.noop),
    ]
