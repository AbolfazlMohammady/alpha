from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0004_category_requests"),
    ]

    operations = [
        migrations.AddField(
            model_name="settlementbatch",
            name="payout_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
