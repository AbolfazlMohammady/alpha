from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("customizer", "0012_print_area_side"),
    ]

    operations = [
        migrations.AlterField(
            model_name="designdraft",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "پیش‌نویس"),
                    ("cart", "در سبد خرید"),
                    ("confirmed", "تأییدشده"),
                    ("expired", "منقضی"),
                ],
                db_index=True,
                default="draft",
                max_length=20,
            ),
        ),
    ]
