from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="BackupSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_key", models.BooleanField(default=True, editable=False, unique=True)),
                ("enabled", models.BooleanField(default=True, verbose_name="فعال")),
                ("frequency", models.CharField(choices=[("daily", "روزانه"), ("weekly", "هفتگی"), ("monthly", "ماهانه")], default="weekly", max_length=20, verbose_name="دوره")),
                ("run_time", models.TimeField(default="03:00", verbose_name="ساعت اجرا")),
                ("weekday", models.PositiveSmallIntegerField(choices=[(0, "دوشنبه"), (1, "سه‌شنبه"), (2, "چهارشنبه"), (3, "پنج‌شنبه"), (4, "جمعه"), (5, "شنبه"), (6, "یکشنبه")], default=5, verbose_name="روز هفته")),
                ("day_of_month", models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 29)], default=1, verbose_name="روز ماه")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "تنظیمات پشتیبان‌گیری", "verbose_name_plural": "تنظیمات پشتیبان‌گیری"},
        ),
        migrations.CreateModel(
            name="BackupRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("filename", models.CharField(max_length=500)),
                ("status", models.CharField(choices=[("running", "در حال اجرا"), ("success", "موفق"), ("failed", "ناموفق")], default="running", max_length=20)),
                ("trigger", models.CharField(choices=[("scheduled", "خودکار"), ("manual", "دستی")], default="scheduled", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("size_bytes", models.BigIntegerField(default=0)),
                ("sha256", models.CharField(blank=True, default="", max_length=64)),
                ("storage_backend", models.CharField(default="local", max_length=30)),
                ("remote_key", models.CharField(blank=True, default="", max_length=500)),
                ("encrypted", models.BooleanField(default=False)),
                ("includes_database", models.BooleanField(default=False)),
                ("includes_media", models.BooleanField(default=False)),
                ("includes_project", models.BooleanField(default=False)),
                ("error_message", models.TextField(blank=True, default="")),
                ("initiated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_backups", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(fields=("-created_at",), name="backup_created_idx"),
                    models.Index(fields=("status", "-created_at"), name="backup_status_idx"),
                ],
            },
        ),
    ]
