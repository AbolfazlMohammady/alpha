from __future__ import annotations

import json
import random
import re

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Case, CharField, Count, Exists, F, IntegerField, Max, Min, OuterRef, Prefetch, Q, Subquery, Sum, Value, When
from django.db.models.functions import Concat
from django.http import HttpResponsePermanentRedirect
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.safestring import mark_safe
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView, ListView

from .models import (
    Category,
    ContactPageSettings,
    Product,
    ProductComment,
    ProductImage,
    ProductVariant,
    ProductSize,
    CONTACT_PAGE_CACHE_KEY,
)
from apps.saved.models import FavoriteProduct

AUTH_USER_SESSION_KEY = "_auth_user_id"
CATEGORY_NAV_CACHE_KEY = "babaei:shop:active-categories:v2"
CATEGORY_NAV_CACHE_TTL = 300
SIZE_NAV_CACHE_KEY = "babaei:shop:active-sizes:v2"
SIZE_NAV_CACHE_TTL = 300
SIMILAR_PRODUCT_IDS_CACHE_KEY = "babaei:shop:active-product-ids:v1"
SIMILAR_PRODUCT_IDS_CACHE_TTL = 300
CONTACT_PAGE_CACHE_TTL = 86400


def get_random_similar_product_ids(exclude_product_id, limit=8):
    """Return a small random sample without database ORDER BY RANDOM()."""
    candidate_ids = cache.get(SIMILAR_PRODUCT_IDS_CACHE_KEY)
    if candidate_ids is None:
        candidate_ids = list(
            Product.objects.filter(
                is_active=True,
                category__is_active=True,
            ).values_list("id", flat=True)
        )
        cache.set(SIMILAR_PRODUCT_IDS_CACHE_KEY, candidate_ids, SIMILAR_PRODUCT_IDS_CACHE_TTL)

    candidate_ids = [product_id for product_id in candidate_ids if product_id != exclude_product_id]
    if len(candidate_ids) > limit:
        return random.sample(candidate_ids, limit)
    return candidate_ids




def get_active_categories():
    categories = cache.get(CATEGORY_NAV_CACHE_KEY)
    if categories is None:
        categories = list(
            Category.objects.filter(is_active=True)
            .annotate(product_count=Count("products", filter=Q(products__is_active=True)))
            .only("id", "name", "slug", "image")
            .order_by("sort_order", "name")
        )
        cache.set(CATEGORY_NAV_CACHE_KEY, categories, CATEGORY_NAV_CACHE_TTL)
    return categories


def get_active_sizes():
    sizes = cache.get(SIZE_NAV_CACHE_KEY)
    if sizes is None:
        sizes = list(
            ProductSize.objects.filter(is_active=True)
            .only("id", "name", "slug", "sort_order")
            .order_by("sort_order", "name")
        )
        cache.set(SIZE_NAV_CACHE_KEY, sizes, SIZE_NAV_CACHE_TTL)
    return sizes


def absolute_url(request, path):
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{settings.SITE_URL}{path}"


def schema_json(data):
    return mark_safe(json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c"))


def toman_to_irr(value):
    return value * 10


def price_annotations():
    effective_price = Case(
        When(use_product_price=True, then=F("product__base_price")),
        default=F("price"),
        output_field=IntegerField(),
    )
    effective_compare = Case(
        When(use_product_price=True, then=F("product__compare_at_price")),
        default=F("compare_at_price"),
        output_field=IntegerField(),
    )
    variants = ProductVariant.objects.filter(product_id=OuterRef("pk"), is_active=True).annotate(
        effective_price=effective_price,
        effective_compare=effective_compare,
    ).order_by("effective_price", "id")
    max_variants = ProductVariant.objects.filter(product_id=OuterRef("pk"), is_active=True).annotate(
        effective_price=effective_price,
    ).order_by("-effective_price", "id")
    return (
        Subquery(variants.values("effective_price")[:1], output_field=IntegerField()),
        Subquery(variants.values("effective_compare")[:1], output_field=IntegerField()),
        Subquery(max_variants.values("effective_price")[:1], output_field=IntegerField()),
    )


def catalog_price_bounds(queryset):
    product_ids = queryset.values("pk")
    effective_price = Case(
        When(use_product_price=True, then=F("product__base_price")),
        default=F("price"),
        output_field=IntegerField(),
    )
    variant_prices = ProductVariant.objects.filter(
        product_id__in=product_ids,
        is_active=True,
    ).annotate(effective_price=effective_price).aggregate(
        min_price=Min("effective_price"),
        max_price=Max("effective_price"),
    )

    if variant_prices["min_price"] is not None:
        return variant_prices["min_price"], variant_prices["max_price"] or variant_prices["min_price"]

    base_prices = queryset.aggregate(
        min_price=Min("base_price"),
        max_price=Max("base_price"),
    )
    return base_prices["min_price"] or 0, base_prices["max_price"] or 0


def primary_image_annotations():
    images = ProductImage.objects.filter(product_id=OuterRef("pk"), image_type=ProductImage.ImageType.PRIMARY).order_by("sort_order", "id")
    image_path = Subquery(images.values("image")[:1], output_field=CharField(max_length=500))
    image_alt = Subquery(images.values("alt_text")[:1], output_field=CharField(max_length=180))
    return Concat(Value(settings.MEDIA_URL), image_path, output_field=CharField(max_length=520)), image_alt


def card_annotations(request):
    primary_image_url, primary_image_alt = primary_image_annotations()
    has_variants = ProductVariant.objects.filter(product_id=OuterRef("pk"), is_active=True)
    annotations = {
        "primary_image_url": primary_image_url,
        "primary_image_alt": primary_image_alt,
        "has_variants": Exists(has_variants),
    }
    if request.user.is_authenticated:
        annotations["is_favorite"] = Exists(
            FavoriteProduct.objects.filter(user_id=request.user.id, product_id=OuterRef("pk"))
        )
    else:
        annotations["is_favorite"] = Value(False)
    return annotations


def variant_exists_for_product(*, size_slug=None, min_price=None, max_price=None):
    """Build a correlated variant EXISTS query without joining the catalog rows."""
    qs = ProductVariant.objects.filter(
        product_id=OuterRef("pk"),
        is_active=True,
    )

    if size_slug:
        qs = qs.filter(size__is_active=True, size__slug=size_slug)

    effective_price = Case(
        When(use_product_price=True, then=OuterRef("base_price")),
        default=F("price"),
        output_field=IntegerField(),
    )
    qs = qs.annotate(_effective_price=effective_price)

    if min_price is not None:
        qs = qs.filter(_effective_price__gte=min_price)
    if max_price is not None:
        qs = qs.filter(_effective_price__lte=max_price)

    return Exists(qs)


def variant_search_exists(term):
    """Search variant text through EXISTS so one product never multiplies into N rows."""
    return Exists(
        ProductVariant.objects.filter(
            product_id=OuterRef("pk"),
            is_active=True,
        ).filter(
            Q(sku__icontains=term)
            | Q(color__name__icontains=term)
            | Q(size__name__icontains=term)
        )
    )


class ShopSearchView(ListView):
    template_name = "shop/search.html"
    context_object_name = "products"
    paginate_by = 12

    @staticmethod
    def _normalize(value):
        value = (value or "").strip().lower()
        value = value.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
        value = value.replace("ة", "ه")
        value = value.replace("ۀ", "ه")
        value = value.replace("\u200c", " ")
        value = re.sub(r"[\u064b-\u065f\u0670]", "", value)
        value = re.sub(r"[\u0660-\u0669]", lambda m: str(ord(m.group()) - 0x0660), value)
        value = re.sub(r"[\u06f0-\u06f9]", lambda m: str(ord(m.group()) - 0x06f0), value)
        value = re.sub(r"[^\w\s\-]", " ", value, flags=re.UNICODE)
        return re.sub(r"\s+", " ", value).strip()

    def get_queryset(self):
        raw_query = self.request.GET.get("q", "")
        query = self._normalize(raw_query)

        # Opening the search page, opening the navbar search, and an empty
        # submission must not touch Product at all. QuerySet.none() stays lazy
        # and Django can render it without issuing a catalogue SELECT.
        if not query:
            return Product.objects.none()

        # A phrase is kept intact for exact/contains ranking, while each token
        # must independently match at least one searchable product field.
        phrase_variants = {query, query.replace(" ", ""), query.replace(" ", "\u200c")}
        terms = [term for term in query.split(" ") if len(term) >= 1][:8]

        searchable = (
            Q(name__icontains=query)
            | Q(slug__icontains=query)
            | Q(short_description__icontains=query)
            | Q(description__icontains=query)
            | Q(seo_title__icontains=query)
            | Q(seo_description__icontains=query)
            | Q(category__name__icontains=query)
            | variant_search_exists(query)
        )

        # AND across tokens makes searches such as "مشکی L" precise instead of
        # returning every row that happens to contain either word.
        for term in terms:
            term_q = (
                Q(name__icontains=term)
                | Q(slug__icontains=term)
                | Q(short_description__icontains=term)
                | Q(description__icontains=term)
                | Q(seo_title__icontains=term)
                | Q(seo_description__icontains=term)
                | Q(category__name__icontains=term)
                | variant_search_exists(term)
            )
            searchable &= term_q

        exact_q = Q()
        for variant in phrase_variants:
            exact_q |= Q(name__iexact=variant) | Q(slug__iexact=variant)

        starts_q = Q(name__istartswith=query) | Q(slug__istartswith=query)
        category_q = Q(category__name__icontains=query)
        description_q = (
            Q(short_description__icontains=query)
            | Q(description__icontains=query)
            | Q(seo_title__icontains=query)
            | Q(seo_description__icontains=query)
        )

        variant_q = variant_search_exists(query)

        variant_price, variant_compare_price, variant_max_price = price_annotations()

        return (
            Product.objects.filter(
                is_active=True,
                category__is_active=True,
            )
            .filter(searchable)
            .select_related("category")
            .annotate(
                search_exact=Case(
                    When(exact_q, then=1000),
                    When(starts_q, then=800),
                    When(category_q, then=500),
                    When(variant_q, then=450),
                    When(description_q, then=300),
                    default=100,
                    output_field=IntegerField(),
                ),
                **card_annotations(self.request),
                listed_price=variant_price,
                listed_compare_price=variant_compare_price,
                listed_max_price=variant_max_price,
            )
            .prefetch_related(
                Prefetch(
                    "images",
                    queryset=ProductImage.objects.filter(
                        image_type=ProductImage.ImageType.PRIMARY
                    ).order_by("sort_order", "id")[:1],
                    to_attr="card_images",
                )
            )
            .order_by("-search_exact", "-is_featured", "-created_at", "id")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = get_active_categories()
        context["has_dark_hero"] = True
        context["search_query"] = self._normalize(self.request.GET.get("q", ""))
        context["search_has_query"] = bool(context["search_query"])
        context["canonical_url"] = absolute_url(self.request, self.request.path)
        context["og_title"] = "جستجوی محصولات | BABAEI"
        context["og_description"] = "جستجوی دقیق محصولات، تیشرت‌ها و لباس‌های BABAEI."
        return context


class ShopIndexView(ListView):
    template_name = "shop/index.html"
    context_object_name = "products"
    paginate_by = 12

    def get_queryset(self):
        variant_price, variant_compare_price, variant_max_price = price_annotations()
        annotations = card_annotations(self.request)
        card_images = ProductImage.objects.annotate(
            type_priority=Case(
                When(image_type=ProductImage.ImageType.PRIMARY, then=0),
                default=1,
                output_field=IntegerField(),
            )
        ).order_by("type_priority", "sort_order", "id")[:2]

        queryset = Product.objects.filter(
            is_active=True,
            category__is_active=True,
        ).select_related("category").annotate(
            listed_price=variant_price,
            listed_compare_price=variant_compare_price,
            listed_max_price=variant_max_price,
            **annotations,
        ).prefetch_related(
            Prefetch("images", queryset=card_images, to_attr="card_images")
        )

        category = self.request.GET.get("category")
        if category:
            queryset = queryset.filter(category__slug=category)

        size = self.request.GET.get("size") or None

        min_price = None
        raw_min_price = self.request.GET.get("min_price")
        if raw_min_price:
            try:
                min_price = int(raw_min_price)
            except (TypeError, ValueError):
                pass

        max_price = None
        raw_max_price = self.request.GET.get("max_price")
        if raw_max_price:
            try:
                max_price = int(raw_max_price)
            except (TypeError, ValueError):
                pass

        # EXISTS keeps the Product row at one row per product. The previous
        # reverse-FK filter joined every matching variant and then needed
        # DISTINCT, which becomes expensive as a product accumulates variants.
        queryset = queryset.filter(
            variant_exists_for_product(
                size_slug=size,
                min_price=min_price,
                max_price=max_price,
            )
        )

        if self.request.GET.get("discount") == "1":
            queryset = queryset.filter(listed_compare_price__gt=F("listed_price"))

        sort = self.request.GET.get("sort", "featured")
        sort_map = {
            "featured": ("-is_featured", "-created_at"),
            "newest": ("-created_at",),
            "price_asc": ("listed_price", "id"),
            "price_desc": ("-listed_price", "id"),
        }
        return queryset.order_by(*sort_map.get(sort, sort_map["featured"]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        products = list(context["products"])
        context["products"] = products

        # The global navbar gets its designer entry from the shared context
        # processor. Keep the shop page consistent with cart/contact pages and
        # do not override that value with product-configuration requirements.
        context["hero_product"] = products[0] if products else None
        context["categories"] = get_active_categories()
        context["sizes"] = get_active_sizes()
        context["filter_category"] = self.request.GET.get("category", "")
        # Which row of the shared filter rail is current: the filtered slug here,
        # self.category.slug on CategoryDetailView.
        context["current_category_slug"] = context["filter_category"]
        # Only this view renders the dark .sh-hero, so only here may the nav
        # start transparent. See templates/includes/shop_header.html.
        context["has_dark_hero"] = True
        # Category clicks refine THIS page instead of navigating away.
        context["catalog_in_page_filter"] = True
        context["filter_sort"] = self.request.GET.get("sort", "featured")
        context["filter_min_price"] = self.request.GET.get("min_price", "")
        context["filter_max_price"] = self.request.GET.get("max_price", "")
        # The slider bounds follow the active category. They used to be computed
        # from every active product on the site, so filtering to a category still
        # showed a price range that category did not have.
        bounds_queryset = Product.objects.filter(is_active=True, category__is_active=True)
        if context["filter_category"]:
            bounds_queryset = bounds_queryset.filter(category__slug=context["filter_category"])
        context["price_min"], context["price_max"] = catalog_price_bounds(bounds_queryset)
        context["filter_size"] = self.request.GET.get("size", "")
        context["filter_discount"] = self.request.GET.get("discount") == "1"
        context["canonical_url"] = absolute_url(self.request, self.request.path)
        context["og_title"] = "فروشگاه لباس و تیشرت | BABAEI"
        context["og_description"] = "خرید تیشرت و لباس از BABAEI؛ انتخاب مدل، رنگ و سایز و آماده برای شخصی‌سازی."
        # Was /static/images/home/Tshirt.png: a 1.9 MB product shot at 0.75:1, so
        # link previews both pulled far too much data and cropped badly. Now a
        # purpose-built 1200x630 card (~80 KB).
        context["og_image_url"] = absolute_url(self.request, "/static/images/shop/shop-og.jpg")
        context["website_schema"] = schema_json({"@context": "https://schema.org", "@type": "WebSite", "name": "BABAEI", "url": settings.SITE_URL, "inLanguage": "fa-IR"})
        return context


class CategoryDetailView(ListView):
    template_name = "shop/category.html"
    context_object_name = "products"
    paginate_by = 12

    def get_queryset(self):
        self.category = get_object_or_404(Category.objects.only("id", "name", "slug", "description", "seo_title", "seo_description", "image"), slug=self.kwargs["slug"], is_active=True)
        variant_price, variant_compare_price, variant_max_price = price_annotations()
        annotations = card_annotations(self.request)
        card_images = ProductImage.objects.annotate(
            type_priority=Case(
                When(image_type=ProductImage.ImageType.PRIMARY, then=0),
                default=1,
                output_field=IntegerField(),
            )
        ).order_by("type_priority", "sort_order", "id")[:2]
        queryset = Product.objects.filter(category_id=self.category.id, is_active=True).select_related("category").annotate(listed_price=variant_price, listed_compare_price=variant_compare_price, listed_max_price=variant_max_price, **annotations).prefetch_related(Prefetch("images", queryset=card_images, to_attr="card_images"))

        size = self.request.GET.get("size") or None

        min_price = None
        raw_min_price = self.request.GET.get("min_price")
        if raw_min_price:
            try:
                min_price = int(raw_min_price)
            except (TypeError, ValueError):
                pass

        max_price = None
        raw_max_price = self.request.GET.get("max_price")
        if raw_max_price:
            try:
                max_price = int(raw_max_price)
            except (TypeError, ValueError):
                pass

        # EXISTS keeps the Product row at one row per product. The previous
        # reverse-FK filter joined every matching variant and then needed
        # DISTINCT, which becomes expensive as a product accumulates variants.
        queryset = queryset.filter(
            variant_exists_for_product(
                size_slug=size,
                min_price=min_price,
                max_price=max_price,
            )
        )

        if self.request.GET.get("discount") == "1":
            queryset = queryset.filter(listed_compare_price__gt=F("listed_price"))

        sort = self.request.GET.get("sort", "featured")
        sort_map = {
            "featured": ("-is_featured", "-created_at"),
            "newest": ("-created_at",),
            "price_asc": ("listed_price", "id"),
            "price_desc": ("-listed_price", "id"),
        }
        return queryset.order_by(*sort_map.get(sort, sort_map["featured"]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["category"] = self.category
        context["categories"] = get_active_categories()
        context["sizes"] = get_active_sizes()
        # The category is the page here, not a filter, so filter_category stays
        # empty and no "remove category" chip is offered for the page you are on.
        context["filter_category"] = ""
        context["current_category_slug"] = self.category.slug
        context["has_dark_hero"] = False
        # Here the category is the page path, so its rail links stay canonical.
        context["catalog_in_page_filter"] = False
        context["filter_sort"] = self.request.GET.get("sort", "featured")
        context["filter_size"] = self.request.GET.get("size", "")
        context["filter_discount"] = self.request.GET.get("discount") == "1"
        context["filter_min_price"] = self.request.GET.get("min_price", "")
        context["filter_max_price"] = self.request.GET.get("max_price", "")
        base_price_queryset = Product.objects.filter(category_id=self.category.id, is_active=True)
        context["price_min"], context["price_max"] = catalog_price_bounds(base_price_queryset)
        context["canonical_url"] = absolute_url(self.request, self.request.path)
        context["og_title"] = self.category.seo_title or self.category.name
        context["og_description"] = self.category.seo_description or self.category.description or self.category.name
        context["og_image_url"] = absolute_url(self.request, self.category.image.url) if self.category.image else None
        context["category_schema"] = schema_json({"@context": "https://schema.org", "@type": "CollectionPage", "name": self.category.name, "url": context["canonical_url"], "description": self.category.seo_description or self.category.description, "inLanguage": "fa-IR"})
        return context

    def get(self, request, *args, **kwargs):
        if request.GET.get("page") == "1":
            return HttpResponsePermanentRedirect(request.path)
        return super().get(request, *args, **kwargs)

class ProductCommentAddView(LoginRequiredMixin, View):
    login_url = "users:login"

    def post(self, request, slug):
        product = get_object_or_404(Product, slug=slug, is_active=True, category__is_active=True)
        body = (request.POST.get("body") or "").strip()
        rating_raw = (request.POST.get("rating") or "").strip()
        if not body:
            messages.error(request, "متن نظر را وارد کنید.")
            return redirect(f"{product.get_absolute_url()}#comments")
        rating = None
        if rating_raw:
            try:
                rating = int(rating_raw)
            except (TypeError, ValueError):
                rating = None
            if rating is None or not 1 <= rating <= 5:
                messages.error(request, "امتیاز باید بین ۱ تا ۵ باشد.")
                return redirect(f"{product.get_absolute_url()}#comments")
        from apps.orders.models import Order, OrderItem
        verified_purchase = OrderItem.objects.filter(order__user=request.user, order__status=Order.Status.DELIVERED, product=product).exists()
        ProductComment.objects.create(product=product, user=request.user, body=body[:2000], rating=rating, verified_purchase=verified_purchase, status=ProductComment.Status.PENDING)
        messages.success(request, "نظر شما ثبت شد و پس از بررسی نمایش داده می‌شود.")
        return redirect(f"{product.get_absolute_url()}#comments")


class ProductCommentsView(ListView):
    template_name = "shop/product_comments.html"
    context_object_name = "comments"
    paginate_by = 12

    def get_queryset(self):
        self.product = get_object_or_404(Product.objects.select_related("category"), slug=self.kwargs["slug"], is_active=True, category__is_active=True)
        return ProductComment.objects.filter(product=self.product, status=ProductComment.Status.APPROVED).select_related("user").order_by("-created_at", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        summary = ProductComment.objects.filter(product=self.product, status=ProductComment.Status.APPROVED).aggregate(count=Count("id"), average=Avg("rating"))
        context["product"] = self.product
        context["comment_count"] = summary["count"] or 0
        context["comment_average"] = summary["average"]
        return context

class ProductDetailView(DetailView):
    template_name = "shop/product_detail.html"
    context_object_name = "product"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        images = ProductImage.objects.only("id", "product_id", "image", "alt_text", "image_type", "sort_order").annotate(type_priority=Case(When(image_type=ProductImage.ImageType.PRIMARY, then=0), When(image_type=ProductImage.ImageType.DETAIL, then=1), default=2, output_field=IntegerField())).order_by("type_priority", "sort_order", "id")
        from apps.orders.models import Cart, CartItem
        user_id = self.request.session.get(AUTH_USER_SESSION_KEY)
        if user_id:
            cart_quantity = Subquery(CartItem.objects.filter(cart__user_id=user_id, cart__status=Cart.Status.ACTIVE, product_id=OuterRef("product_id"), variant_id=OuterRef("pk")).values("quantity")[:1], output_field=IntegerField())
        else:
            session_key = self.request.session.session_key
            cart_quantity = Subquery(CartItem.objects.filter(cart__session_key=session_key, cart__user__isnull=True, cart__status=Cart.Status.ACTIVE, product_id=OuterRef("product_id"), variant_id=OuterRef("pk")).values("quantity")[:1], output_field=IntegerField()) if session_key else Value(0, output_field=IntegerField())
        variants = ProductVariant.objects.filter(is_active=True).select_related("product", "color", "size").only("id", "product_id", "color_id", "size_id", "sku", "price", "compare_at_price", "stock_quantity", "product__id", "product__base_price", "product__compare_at_price", "color__id", "color__name", "color__slug", "color__hex_code", "size__id", "size__name", "size__slug", "size__sort_order").annotate(cart_quantity=cart_quantity).order_by("color__name", "size__sort_order", "size__name")
        return Product.objects.filter(is_active=True, category__is_active=True).select_related("category").prefetch_related(Prefetch("images", queryset=images, to_attr="gallery_images"), Prefetch("variants", queryset=variants, to_attr="active_variants"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.marketplace.models import Vendor, VendorProduct
        from apps.orders.models import Cart, CartItem
        vendor_listings = list(
            VendorProduct.objects.filter(
                product=self.object,
                status=VendorProduct.Status.ACTIVE,
                vendor__status=Vendor.Status.ACTIVE,
                vendor__user__is_active=True,
            )
            .select_related("vendor")
            .prefetch_related("wholesale_tiers")
            .order_by("retail_price", "id")
        )
        context["vendor_listings"] = vendor_listings
        context["marketplace_unavailable"] = (
            self.object.marketplace_only
            and not any(listing.stock_quantity > 0 for listing in vendor_listings)
        )
        cart_listing_data = {}
        listing_ids = [listing.id for listing in vendor_listings]
        if listing_ids:
            cart_lines = CartItem.objects.filter(
                vendor_listing_id__in=listing_ids,
                cart__status=Cart.Status.ACTIVE,
                custom_design__isnull=True,
            )
            if self.request.user.is_authenticated:
                cart_lines = cart_lines.filter(cart__user=self.request.user)
            elif self.request.session.session_key:
                cart_lines = cart_lines.filter(cart__user__isnull=True, cart__session_key=self.request.session.session_key)
            else:
                cart_lines = cart_lines.none()
            cart_listing_data = {
                f'{row["vendor_listing_id"]}:{row["variant_id"] or 0}': row["quantity"]
                for row in cart_lines.values("vendor_listing_id", "variant_id").annotate(quantity=Sum("quantity"))
            }
        context["cart_listing_data"] = schema_json(cart_listing_data)
        canonical_url = absolute_url(self.request, self.request.path)
        breadcrumbs = [{"name": "فروشگاه", "url": absolute_url(self.request, "/shop/")}, {"name": self.object.category.name, "url": absolute_url(self.request, self.object.category.get_absolute_url())}, {"name": self.object.name, "url": canonical_url}]
        context["breadcrumbs"] = breadcrumbs
        context["canonical_url"] = canonical_url
        context["og_title"] = self.object.seo_title or self.object.name
        context["og_description"] = self.object.seo_description or self.object.short_description or self.object.name
        first_image = next((image for image in self.object.gallery_images if image.image), None)
        context["og_image_url"] = absolute_url(self.request, first_image.image.url) if first_image else None
        offers = self.object.active_variants
        prices = [variant.effective_price for variant in offers]
        colors, sizes = [], []
        seen_colors, seen_sizes = set(), set()
        for variant in offers:
            if variant.color_id not in seen_colors:
                colors.append(variant.color)
                seen_colors.add(variant.color_id)
            if variant.size_id not in seen_sizes:
                sizes.append(variant.size)
                seen_sizes.add(variant.size_id)
        context["colors"] = colors
        context["sizes"] = sizes
        context["total_stock"] = sum(variant.stock_quantity for variant in offers)
        approved_comments = ProductComment.objects.filter(product=self.object, status=ProductComment.Status.APPROVED).select_related("user").order_by("-created_at", "-id")
        comment_summary = approved_comments.aggregate(count=Count("id"), average=Avg("rating"))
        context["featured_comments"] = list(approved_comments[:3])
        context["comment_count"] = comment_summary["count"] or 0
        context["comment_average"] = comment_summary["average"]
        # Keep the related shelf random without making the database sort the
        # entire product table on every product-page request.
        similar_ids = get_random_similar_product_ids(self.object.pk, limit=8)
        similar_variant_price, similar_variant_compare_price, _ = price_annotations()
        similar_has_variants = Exists(
            ProductVariant.objects.filter(product_id=OuterRef("pk"), is_active=True)
        )
        similar_is_favorite = (
            Exists(
                FavoriteProduct.objects.filter(
                    user_id=self.request.user.id,
                    product_id=OuterRef("pk"),
                )
            )
            if self.request.user.is_authenticated
            else Value(False)
        )
        similar_annotations = {
            "has_variants": similar_has_variants,
            "is_favorite": similar_is_favorite,
        }
        similar_images = ProductImage.objects.annotate(
            type_priority=Case(
                When(image_type=ProductImage.ImageType.PRIMARY, then=0),
                default=1,
                output_field=IntegerField(),
            )
        ).order_by("type_priority", "sort_order", "id")[:2]

        if similar_ids:
            rank = Case(
                *[When(pk=product_id, then=position) for position, product_id in enumerate(similar_ids)],
                output_field=IntegerField(),
            )
            context["similar_products"] = list(
                Product.objects.filter(pk__in=similar_ids)
                .select_related("category")
                .annotate(
                    listed_price=similar_variant_price,
                    listed_compare_price=similar_variant_compare_price,
                    **similar_annotations,
                )
                .prefetch_related(Prefetch("images", queryset=similar_images, to_attr="card_images"))
                .order_by(rank)
            )
        else:
            context["similar_products"] = []
        context["cart_variant_data"] = schema_json({str(variant.id): (variant.cart_quantity or 0) for variant in offers})
        context["variant_data"] = schema_json([{ "id": variant.id, "color_id": variant.color_id, "color": variant.color.name, "color_hex": variant.color.hex_code, "size_id": variant.size_id, "size": variant.size.name, "price": variant.effective_price, "compare_at_price": variant.effective_compare_at_price, "stock": variant.stock_quantity, "sku": variant.sku } for variant in offers])
        if offers:
            offer_data = {"@type": "AggregateOffer", "priceCurrency": "IRR", "lowPrice": toman_to_irr(min(prices)), "highPrice": toman_to_irr(max(prices)), "offerCount": len(offers), "availability": "https://schema.org/InStock" if any(v.in_stock for v in offers) else "https://schema.org/OutOfStock"}
        else:
            offer_data = {"@type": "Offer", "priceCurrency": "IRR", "price": toman_to_irr(self.object.base_price), "availability": "https://schema.org/InStock", "url": canonical_url}
        context["product_schema"] = schema_json({"@context": "https://schema.org", "@type": "Product", "name": self.object.name, "description": self.object.seo_description or self.object.short_description or self.object.description, "url": canonical_url, "image": [absolute_url(self.request, image.image.url) for image in self.object.gallery_images if image.image], "brand": {"@type": "Brand", "name": "BABAEI"}, "category": self.object.category.name, "offers": offer_data, "inLanguage": "fa-IR"})
        context["breadcrumb_schema"] = schema_json({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": position, "name": item["name"], "item": item["url"]} for position, item in enumerate(breadcrumbs, start=1)]})
        return context


class ContactPageView(DetailView):
    template_name = "shop/contact.html"
    context_object_name = "contact"

    def get_object(self, queryset=None):
        cached = cache.get(CONTACT_PAGE_CACHE_KEY)
        if cached is not None:
            return cached

        obj = ContactPageSettings.get_solo()
        # Cache only the public, non-user-specific fields. Caching the rendered
        # response would also cache account/cart UI, so keep the cache scoped to
        # this singleton's data instead.
        cached = {
            "title": obj.title,
            "intro": obj.intro,
            "phone": obj.phone,
            "phone_label": obj.phone_label,
        }
        cache.set(CONTACT_PAGE_CACHE_KEY, cached, CONTACT_PAGE_CACHE_TTL)
        return cached

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = get_active_categories()
        context["has_dark_hero"] = False
        context["canonical_url"] = absolute_url(self.request, self.request.path)
        context["og_title"] = "تماس با ما | BABAEI"
        context["og_description"] = self.object["intro"]
        context["breadcrumbs"] = [
            {"name": "فروشگاه", "url": absolute_url(self.request, "/shop/")},
            {"name": self.object["title"], "url": context["canonical_url"]},
        ]
        return context
