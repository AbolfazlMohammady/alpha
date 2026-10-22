from django.db import migrations


DEFAULT_SIZES = (
    ("S", "s", 1),
    ("M", "m", 2),
    ("L", "l", 3),
    ("XL", "xl", 4),
)


def seed_default_sizes(apps, schema_editor):
    ProductSize = apps.get_model("shop", "ProductSize")
    for name, slug, sort_order in DEFAULT_SIZES:
        ProductSize.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "sort_order": sort_order,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0006_merge_0004_product_editor_v2_0005_product_comment"),
    ]

    operations = [
        migrations.RunPython(seed_default_sizes, migrations.RunPython.noop),
    ]
