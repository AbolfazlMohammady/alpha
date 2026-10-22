from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0010_search_performance_indexes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="otp",
            name="code",
            field=models.CharField(max_length=128, verbose_name="کد"),
        ),
        migrations.AddIndex(
            model_name="otp",
            index=models.Index(fields=("expire_at",), name="users_otp_expire_idx"),
        ),
    ]
