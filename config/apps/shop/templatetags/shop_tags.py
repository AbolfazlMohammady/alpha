import os
import re

from django import template
from django.conf import settings
from django.core.cache import cache


register = template.Library()


PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


@register.filter
def price(value):
    if value is None or value == "":
        return "—"
    try:
        formatted = f"{int(value):,}"
    except (TypeError, ValueError):
        return value
    return formatted.translate(PERSIAN_DIGITS)


@register.filter
def discount_percent(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    return f"٪{value}".translate(PERSIAN_DIGITS)


# ---------------------------------------------------------------------------
# Responsive product images
# ---------------------------------------------------------------------------
#
# Product uploads are stored at full camera resolution and were being served
# untouched into every card, with no srcset at all. The card grid now asks for
# derivatives; this tag reports which ones actually exist on disk and stays
# silent about the rest, so the markup degrades to the single original when the
# generator has not been run yet:
#
#     python manage.py generate_image_variants
#
# Nothing here invents a URL for a file that is not there.

# Derived files sit next to the original:
#   media/products/tee.jpg -> media/products/tee-400.webp
def _field(image):
    """Normalise the argument to a file field.

    The templates pass a ProductImage, whose file lives at `.image`. Accepting a
    bare file field too keeps the tag usable from a shell. Reading `.url` off a
    ProductImage directly raises AttributeError, which would silently render an
    empty src on every card.
    """
    nested = getattr(image, "image", None)
    return nested if nested is not None else image


def _variant_url(image, width, fmt):
    """Return the URL of an existing derivative, or None."""
    image = _field(image)
    if not image:
        return None
    name = getattr(image, "name", "") or ""
    if not name:
        return None

    stem, _ext = os.path.splitext(name)
    candidate = f"{stem}-{width}.{fmt}"
    storage = getattr(image, "storage", None)
    if storage is None:
        return None
    try:
        if not storage.exists(candidate):
            return None
        return storage.url(candidate)
    except (OSError, ValueError, NotImplementedError):
        return None


@register.simple_tag
def image_variants(image, widths=None):
    """Build <picture> srcsets for one image.

    Returns a dict:
        width   intrinsic width of the original, or "" when unknown
        avif    srcset string for the AVIF derivatives, or ""
        webp    srcset string for the WebP derivatives, or ""
        src     URL of the original

    The template renders a <source> only for a format that came back non-empty,
    so an ungenerated project keeps working with the plain original.
    """
    field = _field(image)
    if not field:
        return {"width": "", "avif": "", "webp": "", "src": ""}

    if widths is None:
        widths = getattr(settings, "CARD_IMAGE_WIDTHS", (400, 640, 900))

    result = {"width": "", "height": "", "avif": "", "webp": "", "src": ""}
    try:
        result["src"] = field.url
    except (ValueError, AttributeError):
        return result

    name = getattr(field, "name", "") or ""
    cache_key = f"babaei:image-variants:v2:{name}:{','.join(str(w) for w in widths)}"
    cached = cache.get(cache_key)
    if cached is None:
        variants = {"avif": "", "webp": ""}
        smallest = widths[0]

        # Do the storage probes once per image, then reuse the result for the
        # next requests. This matters with object storage because each exists()
        # can become a remote HEAD request.
        for fmt in ("avif", "webp"):
            if not _variant_url(image, smallest, fmt):
                continue

            entries = []
            for width in widths:
                url = _variant_url(image, width, fmt)
                if url:
                    entries.append(f"{url} {width}w")
            if entries:
                variants[fmt] = ", ".join(entries)

        cache.set(cache_key, variants, timeout=600)
        cached = variants

    result.update(cached)

    size_cache_key = f"{cache_key}:size"
    sizes = cache.get(size_cache_key)
    if sizes is None:
        sizes = {"width": "", "height": ""}
        for attr in ("width", "height"):
            try:
                value = getattr(field, attr, "")
                if isinstance(value, int) and value > 0:
                    sizes[attr] = value
            except (OSError, ValueError):
                pass
        cache.set(size_cache_key, sizes, timeout=3600)

    result.update(sizes)
    return result


# ---------------------------------------------------------------------------
# Filter querystrings
# ---------------------------------------------------------------------------

@register.simple_tag(takes_context=True)
def query_without(context, *keys):
    """Rebuild the current querystring with the given keys removed.

    Used by the active-filter chips so each one can drop exactly its own filter
    and keep the rest. `page` always goes, because a filter change invalidates
    the page number.
    """
    request = context.get("request")
    if request is None:
        return "?"
    params = request.GET.copy()
    for key in keys:
        params.pop(key, None)
    params.pop("page", None)
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    """Rebuild the current querystring with the given keys replaced.

    Pagination used to spell out every filter by hand three times:

        ?{% if filter_category %}category={{ filter_category }}&{% endif %}...

    which had to be kept in sync by hand and silently dropped any filter that
    was added later. This keeps everything and only changes the requested key:

        {% query_replace page=number %}
    """
    request = context.get("request")
    if request is None:
        return "?"
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag(takes_context=True)
def filter_count(context):
    """Number of filters currently applied, for the mobile launcher badge."""
    request = context.get("request")
    if request is None:
        return 0
    keys = ("category", "size", "min_price", "max_price", "discount")
    return sum(1 for key in keys if request.GET.get(key))
