from django.db import migrations


DEMO_MODEL_URL = "https://cdn.3dassets.dev/assets/35447/v1/model.glb"


def remove_demo_models(apps, schema_editor):
    DesignerView = apps.get_model("customizer", "DesignerView")
    DesignerView.objects.filter(model_3d_url=DEMO_MODEL_URL, model_3d__isnull=True).update(model_3d_url="")


def restore_demo_models(apps, schema_editor):
    DesignerView = apps.get_model("customizer", "DesignerView")
    first_views = {}
    for view in DesignerView.objects.filter(is_active=True).order_by("product_id", "sort_order", "id"):
        first_views.setdefault(view.product_id, view)
    for view in first_views.values():
        if not view.model_3d and not view.model_3d_url:
            view.model_3d_url = DEMO_MODEL_URL
            view.save(update_fields=["model_3d_url"])


class Migration(migrations.Migration):
    dependencies = [("customizer", "0003_designer_view_3d_model")]

    operations = [migrations.RunPython(remove_demo_models, restore_demo_models)]
