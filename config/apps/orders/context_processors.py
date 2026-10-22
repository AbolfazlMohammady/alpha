from .services import CART_COUNT_SESSION_KEY


def cart_context(request):
    """Expose the cached cart badge without a database query on normal page loads."""
    count = getattr(request, "_babaei_cart_item_count", None)

    if count is None:
        count = request.session.get(CART_COUNT_SESSION_KEY, 0)

    count = int(count or 0)
    request._babaei_cart_item_count = count
    return {
        "cart_item_count": count,
        "cart_url": "/cart/",
    }
