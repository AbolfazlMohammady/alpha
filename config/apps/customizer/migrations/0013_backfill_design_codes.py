from django.db import migrations, models
import apps.customizer.models


def populate_design_codes(apps, schema_editor):
    DesignDraft = apps.get_model("customizer", "DesignDraft")
    existing = set(
        DesignDraft.objects.exclude(design_code__isnull=True)
        .exclude(design_code="")
        .values_list("design_code", flat=True)
    )

    for draft in DesignDraft.objects.filter(design_code__isnull=True).iterator():
        while True:
            code = f"DSN-{__import__('uuid').uuid4().hex[:12].upper()}"
            if code not in existing:
                break
        existing.add(code)
        DesignDraft.objects.filter(pk=draft.pk).update(design_code=code)


class Migration(migrations.Migration):

    dependencies = [
        ("customizer", "0012_print_area_side"),
    ]

    operations = [
        migrations.RunPython(
            populate_design_codes,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="designdraft",
            name="design_code",
            field=models.CharField(
                db_index=True,
                default=apps.customizer.models._design_code,
                editable=False,
                max_length=32,
                unique=True,
                verbose_name="شناسه یکتای طراحی",
            ),
        ),
    ]
