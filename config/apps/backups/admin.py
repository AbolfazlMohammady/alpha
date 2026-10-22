from django.contrib import admin
from .models import BackupRecord, BackupSettings

@admin.register(BackupSettings)
class BackupSettingsAdmin(admin.ModelAdmin):
    list_display = ("frequency", "run_time", "enabled", "updated_at")

@admin.register(BackupRecord)
class BackupRecordAdmin(admin.ModelAdmin):
    list_display = ("filename", "status", "trigger", "size_bytes", "storage_backend", "encrypted", "created_at")
    list_filter = ("status", "trigger", "storage_backend", "encrypted")
    readonly_fields = [field.name for field in BackupRecord._meta.fields]
