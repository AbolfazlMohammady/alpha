from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0015_vendor_application_optional_user"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vendorapplication",
            name="contact_email",
            field=models.EmailField(max_length=254),
        ),
    ]
