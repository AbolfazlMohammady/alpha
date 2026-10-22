from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0007_merge_20260929_1119"),
    ]

    operations = [
        migrations.AddField(
            model_name="address",
            name="is_for_other",
            field=models.BooleanField(
                default=False,
                help_text="اگر این گزینه فعال باشد، نام تحویل‌گیرنده را وارد کنید.",
                verbose_name="این آدرس برای شخص دیگری است",
            ),
        ),
        migrations.AddField(
            model_name="address",
            name="recipient_name",
            field=models.CharField(
                blank=True,
                default="",
                max_length=200,
                verbose_name="نام تحویل‌گیرنده",
            ),
        ),
        migrations.AddConstraint(
            model_name="address",
            constraint=models.CheckConstraint(
                check=Q(is_for_other=False) | ~Q(recipient_name=""),
                name="users_address_other_recipient_name_required",
            ),
        ),
    ]
