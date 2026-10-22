from django.contrib.sitemaps import Sitemap

from .models import Category, Product


class ShopSitemap(Sitemap):
    changefreq = "daily"
    priority = 1.0

    def items(self):
        return ["shop:index", "shop:contact"]

    def location(self, item):
        return "/shop/" if item == "shop:index" else "/shop/contact/"


class CategorySitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return Category.objects.filter(is_active=True).only("id", "slug", "updated_at")

    def lastmod(self, obj):
        return obj.updated_at


class ProductSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.9

    def items(self):
        return Product.objects.filter(is_active=True, category__is_active=True).only(
            "id", "slug", "updated_at", "category_id"
        )

    def lastmod(self, obj):
        return obj.updated_at


sitemaps = {
    "shop": ShopSitemap,
    "categories": CategorySitemap,
    "products": ProductSitemap,
}
