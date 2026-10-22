from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("customizer", "0013_design_code_and_cart_status"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="designdraft",
            name="preview_image",
        ),
    ]
