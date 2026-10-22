from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, UpdateView, View

from apps.control_center.views import RoleGuardMixin
from .forms import BackupSettingsForm
from .models import BackupRecord, BackupSettings
from .tasks import create_backup_task
from .services import backup_root, recover_stale_backups


class BackupAccessMixin(RoleGuardMixin):
    """Backup management is restricted to the technical superuser only."""

    def test_func(self):
        return (
            self.request.user.is_authenticated
            and self.request.user.is_active
            and self.request.user.is_superuser
        )


class BackupDashboardView(BackupAccessMixin, ListView):
    template_name = "control_center/backups/dashboard.html"
    context_object_name = "backups"
    paginate_by = 20

    def get_queryset(self):
        return BackupRecord.objects.select_related("initiated_by").order_by("-created_at", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["backup_settings"] = BackupSettings.get_solo()
        context["successful_count"] = BackupRecord.objects.filter(status=BackupRecord.Status.SUCCESS).count()
        context["last_success"] = (
            BackupRecord.objects.filter(status=BackupRecord.Status.SUCCESS)
            .order_by("-finished_at", "-id")
            .first()
        )
        context["running"] = BackupRecord.objects.filter(status=BackupRecord.Status.RUNNING).exists()
        context["retention_backups"] = list(
            BackupRecord.objects.filter(status=BackupRecord.Status.SUCCESS)
            .order_by("-finished_at", "-id")[:5]
        )
        return context


class BackupSettingsView(BackupAccessMixin, UpdateView):
    model = BackupSettings
    form_class = BackupSettingsForm
    template_name = "control_center/backups/settings.html"
    success_url = reverse_lazy("control:backups")

    def get_object(self, queryset=None):
        return BackupSettings.get_solo()

    def form_valid(self, form):
        messages.success(self.request, "تنظیمات پشتیبان‌گیری ذخیره شد.")
        return super().form_valid(form)


class BackupCreateView(BackupAccessMixin, View):
    def post(self, request):
        recover_stale_backups()
        if BackupRecord.objects.filter(status=BackupRecord.Status.RUNNING).exists():
            messages.error(request, "یک بکاپ در حال اجراست؛ لطفاً تا پایان آن صبر کنید.")
            return redirect("control:backups")
        try:
            create_backup_task.delay(
                trigger=BackupRecord.Trigger.MANUAL,
                initiated_by_id=request.user.pk,
            )
        except Exception as exc:
            messages.error(request, f"ارسال درخواست بکاپ ناموفق بود: {exc}")
        else:
            messages.success(request, "درخواست بکاپ ارسال شد و پردازش آن در پس‌زمینه انجام می‌شود.")
        return redirect("control:backups")


class BackupDownloadView(BackupAccessMixin, View):
    """Download a completed local backup without exposing its filesystem path."""

    def get(self, request, pk):
        backup = BackupRecord.objects.filter(
            pk=pk,
            status=BackupRecord.Status.SUCCESS,
            storage_backend="local",
        ).first()
        if backup is None:
            raise Http404("Backup is not available for download.")

        root = backup_root().resolve()
        file_path = (root / backup.filename).resolve()

        # Never allow a database-stored filename to escape BACKUP_ROOT.
        if file_path.parent != root or not file_path.is_file():
            raise Http404("Backup file was not found.")

        return FileResponse(
            open(file_path, "rb"),
            as_attachment=True,
            filename=backup.filename,
        )
