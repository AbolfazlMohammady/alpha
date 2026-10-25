from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0012_minimum_settlement_hold"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="journalline",
            name="journal_line_one_sided_positive",
        ),
        migrations.AddConstraint(
            model_name="journalline",
            constraint=models.CheckConstraint(
                check=models.Q(
                    models.Q(("credit", 0), ("debit__gt", 0)),
                    models.Q(("credit__gt", 0), ("debit", 0)),
                    _connector="OR",
                ),
                name="journal_line_one_sided_positive",
            ),
        ),
    ]
