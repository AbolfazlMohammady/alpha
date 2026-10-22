from __future__ import annotations

from django.conf import settings
from django.db.models import CharField, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Concat
from django.views.generic import TemplateView

from apps.shop.models import Product, ProductImage, ProductVariant
from apps.shop.views import get_active_categories


class HomeView(TemplateView):
    template_name = "home/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        primary_images = ProductImage.objects.filter(
            product_id=OuterRef("pk"),
            image_type=ProductImage.ImageType.PRIMARY,
        ).order_by("sort_order", "id")
        primary_image_url = Concat(
            Value(settings.MEDIA_URL),
            Subquery(primary_images.values("image")[:1], output_field=CharField(max_length=500)),
            output_field=CharField(max_length=520),
        )
        primary_image_alt = Subquery(
            primary_images.values("alt_text")[:1],
            output_field=CharField(max_length=180),
        )
        variant_price = Subquery(
            ProductVariant.objects.filter(
                product_id=OuterRef("pk"),
                is_active=True,
            ).order_by("price", "id").values("price")[:1],
            output_field=IntegerField(),
        )
        context["home_products"] = (
            Product.objects.filter(is_active=True, category__is_active=True)
            .select_related("category")
            .annotate(
                listed_price=variant_price,
                primary_image_url=primary_image_url,
                primary_image_alt=primary_image_alt,
            )
            .order_by("-is_featured", "-created_at")[:4]
        )
        # Category navigation is Redis-cached by get_active_categories().
        context["home_categories"] = get_active_categories()[:4]
        return context
