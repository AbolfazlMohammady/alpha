from django.contrib.admin.apps import AdminConfig


class BabaeiAdminConfig(AdminConfig):
    """Use the restricted technical admin site for BABAEI."""

    default_site = "apps.users.admin_site.BabaeiAdminSite"
