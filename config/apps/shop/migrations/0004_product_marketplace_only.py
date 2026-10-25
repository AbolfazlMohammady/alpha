from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0003_product_discount_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="marketplace_only",
            field=models.BooleanField(
                default=False,
                help_text="برای محصولاتی که توسط فروشنده ثبت شده‌اند و نباید بدون آگهی فعال فروشگاه خریداری شوند.",
                verbose_name="فروش فقط از طریق فروشندگان",
            ),
        ),
    ]
