from math import ceil

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import (
    Case,
    Count,
    Exists,
    IntegerField,
    OuterRef,
    Prefetch,
    Subquery,
    When,
    Window,
)
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.shop.models import Product, ProductImage, ProductVariant

from .models import FavoriteProduct


class FavoritePage:
    """Small paginator that gets the total from the product query itself."""

    def __init__(self, object_list, number, count, per_page):
        self.object_list = object_list
        self.number = number
        self.count = count
        self.per_page = per_page
        self.num_pages = max(1, ceil(count / per_page))
        self.page_range = range(1, self.num_pages + 1)
        self.paginator = self

    def has_previous(self):
        return self.number > 1

    def has_next(self):
        return self.number < self.num_pages

    def has_other_pages(self):
        return self.has_previous() or self.has_next()

    def previous_page_number(self):
        return self.number - 1

    def next_page_number(self):
        return self.number + 1


def _back(request, fallback="users:saved"):
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or fallback)


@require_POST
def toggle_favorite(request, product_id):
    if not request.user.is_authenticated:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({
                "ok": False,
                "login_required": True,
                "login_url": settings.LOGIN_URL,
            }, status=401)
        # The login page is /login/ (settings.LOGIN_URL). The hardcoded
        # /account/login/ that used to sit here was never a route, so an
        # anonymous tap on a heart landed on a 404 instead of the sign-in page.
        return redirect(settings.LOGIN_URL)

    product = get_object_or_404(Product, pk=product_id, is_active=True)
    favorite, created = FavoriteProduct.objects.get_or_create(user=request.user, product=product)
    if not created:
        favorite.delete()
        is_favorite = False
        messages.success(request, "محصول از علاقه‌مندی‌ها حذف شد.")
    else:
        is_favorite = True
        messages.success(request, "محصول به علاقه‌مندی‌ها اضافه شد.")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "is_favorite": is_favorite,
            "product_id": product.id,
        })

    return _back(request)


@login_required
def saved_page(request):
    """
    Keep the favorites page to three application queries:

      1. the authenticated user (from AuthenticationMiddleware)
      2. products + favorite total + lowest active variant price/state
      3. the first two product images

    The previous implementation needed two extra queries for active variants
    and COUNT(*). Variant values are now scalar subqueries in the product
    SELECT, while COUNT(*) is a window value on the same result set.
    """

    per_page = 24
    try:
        page_number = max(1, int(request.GET.get("page", 1)))
    except (TypeError, ValueError):
        page_number = 1

    active_variants = ProductVariant.objects.filter(
        product_id=OuterRef("pk"),
        is_active=True,
    ).order_by("price", "id")

    favorite_products_qs = (
        Product.objects.filter(
            favorited_by__user_id=request.user.id,
            is_active=True,
            category__is_active=True,
        )
        .only(
            "id",
            "name",
            "slug",
            "base_price",
            "compare_at_price",
            "is_featured",
        )
        .annotate(
            listed_price=Subquery(active_variants.values("price")[:1]),
            listed_compare_price=Subquery(
                active_variants.values("compare_at_price")[:1]
            ),
            favorite_total=Window(Count("pk")),
            has_active_variants=Exists(active_variants),
        )
        .prefetch_related(
            Prefetch(
                "images",
                queryset=ProductImage.objects.annotate(
                    type_priority=Case(
                        When(
                            image_type=ProductImage.ImageType.PRIMARY,
                            then=0,
                        ),
                        default=1,
                        output_field=IntegerField(),
                    )
                )
                .only(
                    "id",
                    "product_id",
                    "image",
                    "alt_text",
                    "image_type",
                    "sort_order",
                )
                .order_by("type_priority", "sort_order", "id")[:2],
                to_attr="card_images",
            ),
        )
        .order_by("-favorited_by__created_at")
    )

    offset = (page_number - 1) * per_page
    rows = list(favorite_products_qs[offset:offset + per_page])

    if rows:
        favorite_count = rows[0].favorite_total or 0
    elif page_number > 1:
        # Invalid/high page numbers are uncommon. Re-run page 1 only in this
        # case so a stale URL still renders safely without a COUNT(*) query.
        rows = list(favorite_products_qs[:per_page])
        favorite_count = rows[0].favorite_total if rows else 0
        page_number = 1
    else:
        favorite_count = 0

    for product in rows:
        # Every row came through the user's favorite relation.
        product.is_favorite = True
        product.has_variants = bool(product.has_active_variants)

    page_obj = FavoritePage(
        rows,
        page_number,
        favorite_count,
        per_page,
    )

    return render(
        request,
        "users/account/saved.html",
        {
            "favorite_products": rows,
            "favorite_count": favorite_count,
            "page_obj": page_obj,
        },
    )
