from __future__ import annotations

from pathlib import Path
import random

from django.contrib.staticfiles import finders
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from apps.shop.models import Category, Product, ProductColor, ProductImage, ProductSize, ProductVariant
from .seed_demo_catalog import CATEGORIES, PRODUCTS, COLORS, SIZES


class Command(BaseCommand):
    help = "Seed the BABAEI demo catalog using local static images only. No internet required."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25)

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= len(PRODUCTS):
            raise CommandError(f"--limit must be between 1 and {len(PRODUCTS)}")

        categories = self.seed_categories()
        colors = self.seed_colors()
        sizes = self.seed_sizes()
        products_created = 0
        images_created = 0

        for number, (name, category_slug, price, featured) in enumerate(PRODUCTS[:limit], 1):
            product, created = Product.objects.update_or_create(
                slug=slugify(name, allow_unicode=True),
                defaults={
                    "category": categories[category_slug],
                    "name": name,
                    "short_description": "محصولی با طراحی مینیمال و کیفیت مناسب برای استفاده روزمره.",
                    "description": f"{name} از مجموعه BABAEI؛ طراحی ساده، کیفیت مناسب و مناسب برای استایل شخصی.",
                    "base_price": price,
                    "is_active": True,
                    "is_featured": featured,
                    "seo_title": f"{name} | BABAEI",
                    "seo_description": f"خرید {name} از فروشگاه BABAEI با امکان طراحی اختصاصی.",
                },
            )
            products_created += int(created)
            self.seed_variants(product, colors, sizes, price, number)

            if not ProductImage.objects.filter(product=product, image_type=ProductImage.ImageType.PRIMARY).exists():
                image = self.copy_local_product_image(product, category_slug, number, name)
                images_created += int(image)

        self.stdout.write(self.style.SUCCESS(
            f"Catalog seeded successfully: {limit} products, {images_created} local images, "
            f"{len(colors) * len(sizes) * limit} variants."
        ))

    def seed_categories(self):
        result = {}
        for index, item in enumerate(CATEGORIES):
            category, _ = Category.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "is_active": True,
                    "sort_order": index,
                    "seo_title": f"{item['name']} | BABAEI",
                    "seo_description": f"خرید {item['name']} از فروشگاه BABAEI.",
                },
            )
            self.restore_category_image(category, item["image"])
            result[category.slug] = category
        return result

    def restore_category_image(self, category, filename):
        source = finders.find(f"images/home/{filename}")
        if not source or not Path(source).is_file():
            self.stdout.write(self.style.WARNING(f"Category image not found: {filename}"))
            return
        if category.image and category.image.name:
            return
        with open(source, "rb") as image_file:
            category.image.save(filename, File(image_file), save=True)

    def seed_colors(self):
        result = {}
        for name, slug, hex_code in COLORS:
            color, _ = ProductColor.objects.update_or_create(
                slug=slug,
                defaults={"name": name, "hex_code": hex_code, "is_active": True},
            )
            result[slug] = color
        return result

    def seed_sizes(self):
        # Respect the sizes configured in the system. Only create the old
        # S/M/L/XL demo defaults when the database has no active sizes yet.
        active_sizes = list(
            ProductSize.objects.filter(is_active=True).order_by("sort_order", "name")
        )
        if not active_sizes:
            for name, slug, order in SIZES:
                ProductSize.objects.update_or_create(
                    slug=slug,
                    defaults={
                        "name": name,
                        "sort_order": order,
                        "is_active": True,
                    },
                )
            active_sizes = list(
                ProductSize.objects.filter(is_active=True).order_by("sort_order", "name")
            )
        return {size.slug: size for size in active_sizes}

    def seed_variants(self, product, colors, sizes, price, number):
        for color_slug, color in colors.items():
            for size_slug, size in sizes.items():
                ProductVariant.objects.update_or_create(
                    product=product,
                    color=color,
                    size=size,
                    defaults={
                        "sku": f"BAB-{number:02d}-{color_slug[:3].upper()}-{size_slug.upper()}",
                        "price": price + (50000 if color_slug == "gray" else 0),
                        "use_product_price": False,
                        "stock_quantity": 12,
                        "is_active": True,
                    },
                )

    def copy_local_product_image(self, product, category_slug, number, product_name):
        filename_by_category = {
            "t-shirts": "Tshirt.png",
            "hoodies": "Hoodis.png",
            "oversized": "Oversize.png",
            "accessories": "accsory.png",
        }
        # Every product uses one of the four real homepage/category images.
        # Selection is intentionally random so a category does not always
        # receive the exact same source file on every seed run.
        source_name = random.choice(tuple(filename_by_category.values()))
        source = finders.find(f"images/home/{source_name}")
        if not source or not Path(source).is_file():
            self.stdout.write(self.style.WARNING(f"Product fallback image not found: {source_name}"))
            return False

        filename = f"{slugify(product_name, allow_unicode=True)}-{number}.png"
        with open(source, "rb") as image_file:
            ProductImage.objects.create(
                product=product,
                image=File(image_file, name=filename),
                alt_text=product_name,
                image_type=ProductImage.ImageType.PRIMARY,
                sort_order=0,
            )
        return True
