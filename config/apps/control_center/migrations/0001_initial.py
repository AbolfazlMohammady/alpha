from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=80, verbose_name="عملیات")),
                ("description", models.CharField(max_length=500, verbose_name="شرح")),
                ("method", models.CharField(choices=[("GET", "GET"), ("POST", "POST"), ("PUT", "PUT"), ("PATCH", "PATCH"), ("DELETE", "DELETE"), ("OTHER", "OTHER")], default="GET", max_length=10, verbose_name="متد")),
                ("path", models.CharField(max_length=500, verbose_name="مسیر")),
                ("status_code", models.PositiveSmallIntegerField(default=200, verbose_name="کد پاسخ")),
                ("result", models.CharField(choices=[("success", "موفق"), ("redirect", "انتقال"), ("client_error", "خطای کاربر"), ("server_error", "خطای سرور")], default="success", max_length=20, verbose_name="نتیجه")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP")),
                ("user_agent", models.TextField(blank=True, default="", verbose_name="مرورگر")),
                ("query_string", models.TextField(blank=True, default="", verbose_name="پارامترها")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="زمان")),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="control_audit_logs", to=settings.AUTH_USER_MODEL, verbose_name="کاربر")),
            ],
            options={
                "verbose_name": "گزارش فعالیت",
                "verbose_name_plural": "گزارش فعالیت‌ها",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["-created_at"], name="control_audit_created_idx"),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["actor", "-created_at"], name="control_audit_actor_idx"),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["action", "-created_at"], name="control_audit_action_idx"),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["status_code", "-created_at"], name="control_audit_status_idx"),
        ),
    ]
