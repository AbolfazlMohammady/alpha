from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0014_vendor_application"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vendorapplication",
            name="user",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="vendor_application",
                to="users.user",
            ),
        ),
    ]
