import apps.customizer.models
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customizer", "0018_private_pending_upload_storage"),
    ]

    operations = [
        migrations.AlterField(
            model_name="artwork",
            name="image",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to=apps.customizer.models._asset_path,
                validators=[django.core.validators.FileExtensionValidator(["jpg", "jpeg", "png", "webp"])],
                verbose_name="لیبل آماده",
            ),
        ),
    ]
