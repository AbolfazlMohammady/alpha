from django.db import models
from django.utils.translation import gettext_lazy as _

class BackupSettings(models.Model):
    class Frequency(models.TextChoices):
        DAILY = "daily", _("روزانه")
        WEEKLY = "weekly", _("هفتگی")
        MONTHLY = "monthly", _("ماهانه")

    singleton_key = models.BooleanField(default=True, unique=True, editable=False)
    enabled = models.BooleanField(default=True, verbose_name=_("فعال"))
    frequency = models.CharField(max_length=20, choices=Frequency.choices, default=Frequency.WEEKLY, verbose_name=_("دوره"))
    run_time = models.TimeField(default="03:00", verbose_name=_("ساعت اجرا"))
    weekday = models.PositiveSmallIntegerField(
        default=5,
        choices=((0, _("دوشنبه")), (1, _("سه‌شنبه")), (2, _("چهارشنبه")), (3, _("پنج‌شنبه")), (4, _("جمعه")), (5, _("شنبه")), (6, _("یکشنبه"))),
        verbose_name=_("روز هفته"),
    )
    day_of_month = models.PositiveSmallIntegerField(
        default=1,
        choices=[(day, str(day)) for day in range(1, 29)],
        verbose_name=_("روز ماه"),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("تنظیمات پشتیبان‌گیری")
        verbose_name_plural = _("تنظیمات پشتیبان‌گیری")

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

class BackupRecord(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", _("در حال اجرا")
        SUCCESS = "success", _("موفق")
        FAILED = "failed", _("ناموفق")

    class Trigger(models.TextChoices):
        SCHEDULED = "scheduled", _("خودکار")
        MANUAL = "manual", _("دستی")

    filename = models.CharField(max_length=500)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    trigger = models.CharField(max_length=20, choices=Trigger.choices, default=Trigger.SCHEDULED)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    storage_backend = models.CharField(max_length=30, default="local")
    remote_key = models.CharField(max_length=500, blank=True, default="")
    encrypted = models.BooleanField(default=False)
    includes_database = models.BooleanField(default=False)
    includes_media = models.BooleanField(default=False)
    includes_project = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, default="")
    initiated_by = models.ForeignKey("users.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_backups")

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("-created_at",), name="backup_created_idx"),
            models.Index(fields=("status", "-created_at"), name="backup_status_idx"),
        ]

    def __str__(self):
        return self.filename
