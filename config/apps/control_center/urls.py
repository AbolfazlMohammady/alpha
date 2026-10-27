from functools import wraps

from django.http import HttpResponseForbidden
from django.urls import path
from apps.users.models import RoleUser
from . import views
from apps.backups import views as backup_views

app_name = "control"


def control_center_access(view):
    """Keep seller accounts out of every control-center endpoint, including direct URLs."""
    @wraps(view)
    def guarded_view(request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and getattr(user, "role", None) in {RoleUser.STORE_MANAGER, "مدیر فروشگاه"}:
            return HttpResponseForbidden("دسترسی مدیر فروشگاه به مرکز کنترل مجاز نیست.")
        return view(request, *args, **kwargs)

    return guarded_view

urlpatterns = [
    path("", control_center_access(views.DashboardView.as_view()), name="dashboard"),
    path("orders/", control_center_access(views.OrderListView.as_view()), name="orders"),
    path("orders/<int:pk>/", control_center_access(views.OrderDetailView.as_view()), name="order_detail"),
    path("orders/<int:pk>/workflow/", control_center_access(views.OrderWorkflowActionView.as_view()), name="order_workflow"),
    path("orders/<int:pk>/invoice/", control_center_access(views.OrderInvoiceView.as_view()), name="order_invoice"),
    path("reports/", control_center_access(views.AuditLogListView.as_view()), name="reports"),
    path("contact/", control_center_access(views.ContactPageSettingsView.as_view()), name="contact_settings"),
    path("comments/", control_center_access(views.CommentListView.as_view()), name="comments"),
    path("comments/<int:pk>/<str:action>/", control_center_access(views.CommentModerationView.as_view()), name="comment_moderation"),
    path("backups/", control_center_access(backup_views.BackupDashboardView.as_view()), name="backups"),
    path("backups/settings/", control_center_access(backup_views.BackupSettingsView.as_view()), name="backup_settings"),
    path("backups/create/", control_center_access(backup_views.BackupCreateView.as_view()), name="backup_create"),
    path("backups/<int:pk>/download/", control_center_access(backup_views.BackupDownloadView.as_view()), name="backup_download"),
    path("users/", control_center_access(views.UserListView.as_view()), name="users"),
    path("users/new/", control_center_access(views.UserCreateView.as_view()), name="user_create"),
    path("users/<int:pk>/edit/", control_center_access(views.UserUpdateView.as_view()), name="user_edit"),
    path("users/<int:pk>/delete/", control_center_access(views.UserDeleteView.as_view()), name="user_delete"),
    path("products/", control_center_access(views.ProductListView.as_view()), name="products"),
    path("catalog/", control_center_access(views.CatalogAttributeListView.as_view()), name="catalog"),
    path("3d/", control_center_access(views.ThreeDStudioDashboardView.as_view()), name="3d_dashboard"),
    path("3d/designs/<uuid:uuid>/complete/", control_center_access(views.ThreeDProductionCompletionView.as_view()), name="design_complete"),
    path("3d/pricing/", control_center_access(views.ThreeDStudioPricingView.as_view()), name="3d_pricing"),
    path("3d/designs/<uuid:uuid>/", control_center_access(views.PurchasedDesignDetailView.as_view()), name="design_detail"),
    path("3d/designs/<uuid:uuid>/texts/<int:layer_id>/download/", control_center_access(views.PurchasedDesignTextDownloadView.as_view()), name="design_text_download"),
    path("3d/designs/<uuid:uuid>/labels/<int:artwork_id>/download/", control_center_access(views.PurchasedDesignArtworkDownloadView.as_view()), name="design_artwork_download"),
    path("3d/labels/", control_center_access(views.ArtworkLibraryListView.as_view()), name="artwork_library"),
    path("3d/customer-labels/", control_center_access(views.CustomerArtworkListView.as_view()), name="customer_artworks"),
    path("3d/labels/new/", control_center_access(views.ArtworkCreateView.as_view()), name="artwork_create"),
    path("3d/labels/<int:pk>/edit/", control_center_access(views.ArtworkUpdateView.as_view()), name="artwork_edit"),
    path("3d/labels/<int:pk>/delete/", control_center_access(views.ArtworkDeleteView.as_view()), name="artwork_delete"),
    path("catalog/colors/new/", control_center_access(views.ProductColorCreateView.as_view()), name="color_create"),
    path("catalog/colors/<int:pk>/edit/", control_center_access(views.ProductColorUpdateView.as_view()), name="color_edit"),
    path("catalog/colors/<int:pk>/delete/", control_center_access(views.ProductColorDeleteView.as_view()), name="color_delete"),
    path("catalog/sizes/new/", control_center_access(views.ProductSizeCreateView.as_view()), name="size_create"),
    path("catalog/sizes/<int:pk>/edit/", control_center_access(views.ProductSizeUpdateView.as_view()), name="size_edit"),
    path("catalog/sizes/<int:pk>/delete/", control_center_access(views.ProductSizeDeleteView.as_view()), name="size_delete"),
    path("products/new/", control_center_access(views.ProductCreateView.as_view()), name="product_create"),
    path("products/<int:pk>/edit/", control_center_access(views.ProductUpdateView.as_view()), name="product_edit"),
    path("products/<int:pk>/delete/", control_center_access(views.ProductDeleteView.as_view()), name="product_delete"),
    path("categories/", control_center_access(views.CategoryListView.as_view()), name="categories"),
    path("categories/new/", control_center_access(views.CategoryCreateView.as_view()), name="category_create"),
    path("categories/<int:pk>/edit/", control_center_access(views.CategoryUpdateView.as_view()), name="category_edit"),
    path("categories/<int:pk>/delete/", control_center_access(views.CategoryDeleteView.as_view()), name="category_delete"),
]
