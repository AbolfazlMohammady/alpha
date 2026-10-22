import uuid

from django.db import migrations, models


def generate_artwork_code():
    return f"LBL-{uuid.uuid4().hex[:10].upper()}"


def populate_artwork_codes(apps, schema_editor):
    Artwork = apps.get_model("customizer", "Artwork")
    for artwork in Artwork.objects.filter(code__isnull=True):
        artwork.code = f"LBL-{uuid.uuid4().hex[:10].upper()}"
        artwork.save(update_fields=["code"])


class Migration(migrations.Migration):
    dependencies = [
        ("customizer", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="artwork",
            name="code",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=40,
                null=True,
                unique=True,
                verbose_name="کد لیبل",
            ),
        ),
        migrations.RunPython(populate_artwork_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="artwork",
            name="code",
            field=models.CharField(
                db_index=True,
                default=generate_artwork_code,
                editable=False,
                max_length=40,
                unique=True,
                verbose_name="کد لیبل",
            ),
        ),
    ]
