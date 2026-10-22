from django.contrib import admin
from django.utils.html import format_html

from .models import FavoriteProduct


class FavoriteAdminMixin:
    show_full_result_count = False
    list_per_page = 30


@admin.register(FavoriteProduct)
class FavoriteProductAdmin(FavoriteAdminMixin, admin.ModelAdmin):
    list_display = ("user_display", "product_display", "created_at")
    search_fields = ("user__phone", "user__first_name", "user__last_name", "product__name")
    list_filter = ("created_at", "product__category")
    list_select_related = ("user", "product", "product__category")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    @admin.display(description="کاربر")
    def user_display(self, obj):
        name = f"{obj.user.first_name} {obj.user.last_name}".strip() or "مشتری"
        return format_html('<strong>{}</strong><small class="ba-subline">{}</small>', name, obj.user.phone)

    @admin.display(description="محصول")
    def product_display(self, obj):
        return format_html('<strong>{}</strong><small class="ba-subline">{}</small>', obj.product.name, obj.product.category.name)

