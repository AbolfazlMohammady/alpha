import json
from pathlib import Path

from django.core.management.color import no_style
from django.db import migrations


DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "provinces.json"


def seed_provinces(apps, schema_editor):
    Province = apps.get_model("users", "Province")
    with DATA_FILE.open(encoding="utf-8") as source:
        records = json.load(source)
    db = schema_editor.connection.alias
    Province.objects.using(db).bulk_create(
        [Province(id=row["id"], name=row["name"]) for row in records],
        ignore_conflicts=True,
        batch_size=500,
    )
    statements = schema_editor.connection.ops.sequence_reset_sql(no_style(), [Province])
    with schema_editor.connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_provinces, migrations.RunPython.noop),
    ]
