from django.db import migrations, models
import django.core.validators


DEMO_MODEL_URL = "https://cdn.3dassets.dev/assets/35447/v1/model.glb"


def seed_demo_model(apps, schema_editor):
    DesignerView = apps.get_model("customizer", "DesignerView")
    first_views = {}
    for view in DesignerView.objects.filter(is_active=True).order_by("product_id", "sort_order", "id"):
        first_views.setdefault(view.product_id, view)
    for view in first_views.values():
        if not view.model_3d and not view.model_3d_url:
            view.model_3d_url = DEMO_MODEL_URL
            view.model_3d_scale = 1.0
            view.save(update_fields=["model_3d_url", "model_3d_scale"])


def clear_demo_model(apps, schema_editor):
    DesignerView = apps.get_model("customizer", "DesignerView")
    DesignerView.objects.filter(model_3d_url=DEMO_MODEL_URL).update(model_3d_url="")


class Migration(migrations.Migration):
    dependencies = [
        ("customizer", "0002_demo_designer_setup"),
    ]

    operations = [
        migrations.AddField(
            model_name="designerview",
            name="model_3d",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="customizer/models/%Y/%m/",
                validators=[django.core.validators.FileExtensionValidator(["glb", "gltf"])],
                verbose_name="مدل سه‌بعدی لباس (GLB/GLTF)",
            ),
        ),
        migrations.AddField(
            model_name="designerview",
            name="model_3d_scale",
            field=models.FloatField(default=1.0, validators=[django.core.validators.MinValueValidator(0.01)], verbose_name="مقیاس مدل سه‌بعدی"),
        ),
        migrations.AddField(
            model_name="designerview",
            name="model_3d_url",
            field=models.URLField(blank=True, help_text="برای CDN یا مدل دمو؛ در صورت وجود فایل محلی، فایل اولویت دارد.", verbose_name="آدرس مدل سه‌بعدی"),
        ),
        migrations.RunPython(seed_demo_model, clear_demo_model),
    ]
