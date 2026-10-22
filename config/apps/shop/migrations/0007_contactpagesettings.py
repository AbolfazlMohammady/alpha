from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0006_merge_0004_product_editor_v2_0005_product_comment"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContactPageSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(default="تماس با ما", max_length=120, verbose_name="عنوان")),
                (
                    "intro",
                    models.TextField(
                        default="اگر سوالی داری یا برای سفارش به راهنمایی نیاز داری، با ما در ارتباط باش.",
                        max_length=1000,
                        verbose_name="متن معرفی",
                    ),
                ),
                ("phone", models.CharField(default="", max_length=40, verbose_name="شماره تماس")),
                ("phone_label", models.CharField(default="پشتیبانی و تماس", max_length=80, verbose_name="عنوان شماره")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین بروزرسانی")),
            ],
            options={
                "verbose_name": "تنظیمات صفحه تماس",
                "verbose_name_plural": "تنظیمات صفحه تماس",
            },
        ),
    ]
