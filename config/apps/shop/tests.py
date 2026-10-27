from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import Category, Product, ProductColor, ProductImage, ProductSize, ProductVariant


class ShopModelTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="تیشرت", slug="تیشرت")
        self.product = Product.objects.create(
            category=self.category,
            name="تیشرت مشکی",
            slug="black-tshirt",
            base_price=490000,
            is_active=True,
        )
        self.color = ProductColor.objects.create(name="مشکی", slug="black", hex_code="#000000")
        self.size, _ = ProductSize.objects.get_or_create(slug="l", defaults={"name": "L"})

    def test_variant_reports_stock(self):
        variant = ProductVariant.objects.create(
            product=self.product,
            color=self.color,
            size=self.size,
            sku="BT-BLK-L",
            price=490000,
            stock_quantity=3,
        )
        self.assertTrue(variant.in_stock)

    def test_variant_combination_is_unique_per_product(self):
        ProductVariant.objects.create(
            product=self.product,
            color=self.color,
            size=self.size,
            sku="BT-BLK-L",
            price=490000,
        )

        with self.assertRaises(IntegrityError):
            ProductVariant.objects.create(
                product=self.product,
                color=self.color,
                size=self.size,
                sku="BT-BLK-L-2",
                price=490000,
            )

    def test_only_one_primary_image_is_allowed(self):
        ProductImage.objects.create(
            product=self.product,
            image="products/one.webp",
            image_type=ProductImage.ImageType.PRIMARY,
        )

        with self.assertRaises(IntegrityError):
            ProductImage.objects.create(
                product=self.product,
                image="products/two.webp",
                image_type=ProductImage.ImageType.PRIMARY,
            )

    def test_display_price_uses_base_price(self):
        self.assertEqual(self.product.display_price, 490000)

    def test_variant_can_inherit_product_price_and_discount(self):
        self.product.compare_at_price = 500000
        self.product.base_price = 450000
        self.product.save(update_fields=["base_price", "compare_at_price"])
        variant = ProductVariant.objects.create(
            product=self.product,
            color=self.color,
            size=self.size,
            sku="BT-INHERIT-L",
            price=450000,
            use_product_price=True,
        )
        self.assertEqual(variant.effective_price, 450000)
        self.assertEqual(variant.effective_compare_at_price, 500000)
        self.assertEqual(variant.discount_percent, 10)

    def test_product_specific_colors_can_have_same_slug_on_different_products(self):
        second = Product.objects.create(
            category=self.category,
            name="تیشرت سفید",
            slug="white-tshirt",
            base_price=490000,
        )
        first_color = ProductColor.objects.create(
            product=self.product,
            name="قرمز",
            slug="red",
            hex_code="#FF0000",
        )
        second_color = ProductColor.objects.create(
            product=second,
            name="قرمز",
            slug="red",
            hex_code="#FF0000",
        )
        self.assertNotEqual(first_color.pk, second_color.pk)



class ShopViewTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="تیشرت", slug="تیشرت")
        self.product = Product.objects.create(
            category=self.category,
            name="تیشرت مشکی",
            slug="black-tshirt",
            base_price=490000,
            is_active=True,
        )

    def test_shop_home_is_reachable(self):
        response = self.client.get(reverse("shop:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)
        self.assertContains(response, 'application/ld+json')

    def test_category_is_reachable(self):
        response = self.client.get(reverse("shop:category", kwargs={"slug": self.category.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)
        self.assertContains(response, 'application/ld+json')

    def test_product_detail_is_reachable(self):
        response = self.client.get(reverse("shop:product", kwargs={"slug": self.product.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)
        self.assertContains(response, "لیبلت را روی لباس قرار بده")
        self.assertContains(response, '"@type":"Product"')
        self.assertContains(response, '"@type":"BreadcrumbList"')

    def test_category_page_one_redirects_to_clean_url(self):
        response = self.client.get(
            reverse("shop:category", kwargs={"slug": self.category.slug}),
            {"page": 1},
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], reverse("shop:category", kwargs={"slug": self.category.slug}))

    def test_marketplace_only_products_are_not_mixed_into_platform_catalog(self):
        marketplace_product = Product.objects.create(
            category=self.category,
            name="محصول اختصاصی فروشنده",
            slug="seller-only-product",
            base_price=125000,
            is_active=True,
            marketplace_only=True,
        )
        home = self.client.get(reverse("shop:index"))
        category = self.client.get(reverse("shop:category", kwargs={"slug": self.category.slug}))
        search = self.client.get(reverse("shop:search"), {"q": marketplace_product.name})
        self.assertEqual(home.status_code, 200)
        self.assertEqual(category.status_code, 200)
        self.assertEqual(search.status_code, 200)
        self.assertNotContains(home, marketplace_product.name)
        self.assertNotContains(category, marketplace_product.name)
        self.assertNotContains(search, reverse("shop:product", kwargs={"slug": marketplace_product.slug}))

    def test_shop_prominently_links_to_seller_marketplace(self):
        response = self.client.get(reverse("shop:index"))
        self.assertContains(response, 'href="/marketplace/store/"')
        self.assertContains(response, "خرید از فروشندگان")

    def test_marketplace_only_product_does_not_publish_fake_platform_stock_or_price(self):
        product = Product.objects.create(
            category=self.category,
            name="محصول فقط بازار فروشندگان",
            slug="marketplace-only-detail",
            base_price=990000,
            is_active=True,
            marketplace_only=True,
        )
        response = self.client.get(reverse("shop:product", kwargs={"slug": product.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"availability":"https://schema.org/OutOfStock"')
        self.assertContains(response, 'id="product-price" class="pd-price__value">انتخاب فروشنده</strong>')
        self.assertContains(response, "برای مشاهده قیمت و موجودی، فروشنده را انتخاب کن.")
        self.assertNotContains(response, '"availability":"https://schema.org/InStock","url"')

    def test_inactive_product_is_hidden_from_shop(self):
        self.product.is_active = False
        self.product.save(update_fields=["is_active"])
        response = self.client.get(reverse("shop:index"))
        self.assertNotContains(response, reverse("shop:product", kwargs={"slug": self.product.slug}))

    def test_inactive_category_is_not_public(self):
        self.category.is_active = False
        self.category.save(update_fields=["is_active"])
        response = self.client.get(reverse("shop:category", kwargs={"slug": self.category.slug}))
        self.assertEqual(response.status_code, 404)

    def test_robots_and_sitemap_are_public(self):
        robots = self.client.get(reverse("robots"))
        self.assertEqual(robots.status_code, 200)
        self.assertContains(robots, "Sitemap:")

        sitemap = self.client.get(reverse("sitemap"))
        self.assertEqual(sitemap.status_code, 200)
        self.assertContains(sitemap, "/shop/")
