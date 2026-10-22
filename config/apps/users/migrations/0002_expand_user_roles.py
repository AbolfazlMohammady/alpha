from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("customer", "مشتری"),
                    ("admin", "مدیر"),
                    ("store_manager", "مدیر فروشگاه"),
                    ("order_manager", "مسئول سفارش‌ها"),
                    ("design_manager", "مسئول طراحی"),
                    ("support_manager", "پشتیبانی"),
                    ("blog_manager", "مدیر بلاگ"),
                ],
                default="customer",
                max_length=20,
                verbose_name="نقش",
            ),
        ),
    ]
