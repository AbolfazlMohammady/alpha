from django.core.cache import cache

from apps.customizer.models import DesignerView, PrintArea, PrintAreaView
from apps.shop.models import Product


DESIGNER_NAV_CACHE_KEY = "babaei:nav:designer-product:v3"
DESIGNER_NAV_CACHE_TTL = 300
_NO_DESIGNER = "__no_designer__"


def designer_navigation(request):
    """
    Expose one active product for the global design entry point.

    The designer page can work in 2D when a product is not yet fully
    configured for 3D, so the navbar must not hide the entry merely because
    DesignerView/PrintArea/PrintAreaView configuration is incomplete.
    """
    product = cache.get(DESIGNER_NAV_CACHE_KEY)

    if product == _NO_DESIGNER:
        product = None
    elif product is None:
        product = (
            Product.objects.filter(
                is_active=True,
                category__is_active=True,
            )
            .only("id", "uuid", "name")
            .order_by("-is_featured", "created_at", "id")
            .first()
        )

        cache.set(
            DESIGNER_NAV_CACHE_KEY,
            product if product is not None else _NO_DESIGNER,
            DESIGNER_NAV_CACHE_TTL,
        )

    return {"designer_product": product}
