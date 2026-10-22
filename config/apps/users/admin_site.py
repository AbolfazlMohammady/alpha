from django.contrib import admin
from django.http import Http404


class BabaeiAdminSite(admin.AdminSite):
    """Technical Django admin is available to superusers only."""

    site_header = "BABAEI Administration"
    site_title = "BABAEI Admin"
    index_title = "مدیریت فنی"

    def has_permission(self, request):
        return bool(
            request.user.is_authenticated
            and request.user.is_active
            and request.user.is_superuser
        )

    def login(self, request, extra_context=None):
        # Django's built-in admin login page must not be exposed publicly.
        # The designated superuser authenticates through the normal BABAEI
        # login flow first, then can open /admin/.
        if not request.user.is_authenticated or not request.user.is_superuser:
            raise Http404
        return super().login(request, extra_context=extra_context)
