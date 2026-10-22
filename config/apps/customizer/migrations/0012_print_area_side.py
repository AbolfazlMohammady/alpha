from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("customizer", "0011_default_artwork_price"),
    ]

    operations = [
        migrations.AddField(
            model_name="printarea",
            name="side",
            field=models.CharField(
                choices=[("front", "جلو"), ("back", "پشت")],
                db_index=True,
                default="front",
                max_length=10,
                verbose_name="سمت لباس",
            ),
        ),
    ]
