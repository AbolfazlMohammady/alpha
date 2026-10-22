from django import template

from ..models import FavoriteProduct

register = template.Library()


@register.simple_tag
def saved_status(user, product):
    if not getattr(user, "is_authenticated", False):
        return {"favorite": False, "saved": False}
    return {
        "favorite": FavoriteProduct.objects.filter(user=user, product=product).exists(),
    }
