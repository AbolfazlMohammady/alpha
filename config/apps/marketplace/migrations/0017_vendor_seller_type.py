from django.db import migrations, models


def preserve_existing_wholesale_vendors(apps, schema_editor):
    Vendor = apps.get_model("marketplace", "Vendor")
    VendorProduct = apps.get_model("marketplace", "VendorProduct")
    vendor_ids = VendorProduct.objects.filter(wholesale_enabled=True).values_list("vendor_id", flat=True).distinct()
    Vendor.objects.filter(pk__in=vendor_ids).update(seller_type="both")


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0016_require_vendor_application_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="vendor",
            name="seller_type",
            field=models.CharField(
                choices=[("retail", "خرده‌فروشی"), ("wholesale", "عمده‌فروشی"), ("both", "خرده‌فروشی و عمده‌فروشی")],
                default="retail",
                max_length=12,
            ),
        ),
        migrations.RunPython(preserve_existing_wholesale_vendors, migrations.RunPython.noop),
    ]
