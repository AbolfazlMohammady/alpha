from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("saved", "0002_rename_saved_favor_user_id_8d8f4d_idx_saved_favor_user_id_5d9438_idx_and_more"),
    ]

    operations = [
        migrations.DeleteModel(
            name="SavedProduct",
        ),
    ]
