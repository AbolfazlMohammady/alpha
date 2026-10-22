from django.urls import path
from . import views

app_name = "backups"

urlpatterns = [
    path("", views.BackupDashboardView.as_view(), name="dashboard"),
    path("settings/", views.BackupSettingsView.as_view(), name="settings"),
    path("create/", views.BackupCreateView.as_view(), name="create"),
]
