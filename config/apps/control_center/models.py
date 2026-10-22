from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditLog(models.Model):
    class Method(models.TextChoices):
        GET = "GET", "GET"
        POST = "POST", "POST"
        PUT = "PUT", "PUT"
        PATCH = "PATCH", "PATCH"
        DELETE = "DELETE", "DELETE"
        OTHER = "OTHER", "OTHER"

    class Result(models.TextChoices):
        SUCCESS = "success", _("موفق")
        REDIRECT = "redirect", _("انتقال")
        CLIENT_ERROR = "client_error", _("خطای کاربر")
        SERVER_ERROR = "server_error", _("خطای سرور")

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="control_audit_logs",
        verbose_name=_("کاربر"),
    )
    action = models.CharField(_("عملیات"), max_length=80)
    description = models.CharField(_("شرح"), max_length=500)
    method = models.CharField(_("متد"), max_length=10, choices=Method.choices, default=Method.GET)
    path = models.CharField(_("مسیر"), max_length=500)
    status_code = models.PositiveSmallIntegerField(_("کد پاسخ"), default=200)
    result = models.CharField(_("نتیجه"), max_length=20, choices=Result.choices, default=Result.SUCCESS)
    ip_address = models.GenericIPAddressField(_("IP"), null=True, blank=True)
    user_agent = models.TextField(_("مرورگر"), blank=True, default="")
    query_string = models.TextField(_("پارامترها"), blank=True, default="")
    created_at = models.DateTimeField(_("زمان"), auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("-created_at",), name="control_audit_created_idx"),
            models.Index(fields=("actor", "-created_at"), name="control_audit_actor_idx"),
            models.Index(fields=("action", "-created_at"), name="control_audit_action_idx"),
            models.Index(fields=("status_code", "-created_at"), name="control_audit_status_idx"),
        ]
        verbose_name = _("گزارش فعالیت")
        verbose_name_plural = _("گزارش فعالیت‌ها")

    def __str__(self):
        return f"{self.actor_id} - {self.action} - {self.created_at:%Y-%m-%d %H:%M:%S}"
