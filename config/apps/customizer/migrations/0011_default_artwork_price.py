from django.db import migrations, models
from django.core.validators import MinValueValidator

def set_default_artwork_price(apps, schema_editor):
    Artwork = apps.get_model("customizer", "Artwork")
    Artwork.objects.filter(
        source="library",
        base_price=0,
    ).update(base_price=100000)


class Migration(migrations.Migration):

    dependencies = [
        ("customizer", "0010_phase2_design_schema"),
    ]

    operations = [
        migrations.AlterField(
            model_name="artwork",
            name="base_price",
            field=models.PositiveBigIntegerField(default=100000, validators=[MinValueValidator(0)], verbose_name="قیمت پایه لیبل"),
        ),
        migrations.RunPython(set_default_artwork_price, migrations.RunPython.noop),
    ]
