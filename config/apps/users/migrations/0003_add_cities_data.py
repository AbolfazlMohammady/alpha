import json
from pathlib import Path

from django.core.management.color import no_style
from django.db import migrations


DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "cities.json"


def seed_cities(apps, schema_editor):
    City = apps.get_model("users", "City")
    with DATA_FILE.open(encoding="utf-8") as source:
        records = json.load(source)
    db = schema_editor.connection.alias
    City.objects.using(db).bulk_create(
        [
            City(id=row["id"], name=row["name"], province_id=row["province_id"])
            for row in records
        ],
        ignore_conflicts=True,
        batch_size=500,
    )
    statements = schema_editor.connection.ops.sequence_reset_sql(no_style(), [City])
    with schema_editor.connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_add_provinces_data"),
    ]

    operations = [
        migrations.RunPython(seed_cities, migrations.RunPython.noop),
    ]
