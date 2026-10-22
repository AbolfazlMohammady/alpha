from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0011_otp_security_cleanup"),
    ]

    operations = [
        migrations.AddField(
            model_name="otp",
            name="attempts",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="تعداد تلاش"),
        ),
    ]
