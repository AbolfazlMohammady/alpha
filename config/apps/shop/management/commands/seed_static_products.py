from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.shop.models import (
    Category,
    Product,
    ProductColor,
    ProductComment,
    ProductImage,
    ProductSize,
    ProductVariant,
)
from apps.users.models import User


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}

DEFAULT_CATEGORIES = [("تیشرت", "t-shirts"), ("هودی", "hoodies"), ("اورسایز", "oversized"), ("اکسسوری", "accessories")]
DEFAULT_COLORS = [("مشکی", "black", "#111111"), ("سفید", "white", "#F5F5F2"), ("طوسی", "gray", "#8A8A86")]
DEFAULT_SIZES = [("S", "s", 1), ("M", "m", 2), ("L", "l", 3), ("XL", "xl", 4)]

PRODUCT_TEMPLATES = [
    ("محصول جدید", "t-shirts"),
    ("تیشرت استایل", "t-shirts"),
    ("تیشرت مینیمال", "t-shirts"),
    ("تیشرت روزمره", "t-shirts"),
    ("هودی کلاسیک", "hoodies"),
    ("هودی استایل", "hoodies"),
    ("هودی مینیمال", "hoodies"),
    ("اورسایز کلاسیک", "oversized"),
    ("اورسایز استایل", "oversized"),
    ("اورسایز مینیمال", "oversized"),
    ("اکسسوری روزمره", "accessories"),
    ("اکسسوری کلاسیک", "accessories"),
]

COMMENT_TEXTS = [
    ("کیفیت محصول خیلی خوبه و دوختش تمیزه.", 5),
    ("رنگ و فرم محصول دقیقاً مطابق توضیحات بود.", 5),
    ("برای استفاده روزمره انتخاب خیلی خوبیه.", 4),
]


class Command(BaseCommand):
    """
    Create catalog products automatically from images already stored in static.

    Each image becomes one product, receives all active colors/sizes as variants,
    and gets a primary ProductImage. Running the command again updates the same
    products instead of creating duplicates.
    """

    help = "Create/update products automatically from images in the static/images folder."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=30,
            help="Maximum number of images/products to process (default: 30).",
        )
        parser.add_argument(
            "--image-dir",
            default="",
            help="Optional image directory relative to BASE_DIR. Defaults to static/images.",
        )
        parser.add_argument(
            "--stock",
            type=int,
            default=12,
            help="Initial stock for every color/size variant.",
        )
        parser.add_argument(
            "--with-comments",
            action="store_true",
            help="Add demo comments using the first active non-superuser account.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        count = options["count"]
        stock = options["stock"]

        if count < 1 or count > 100:
            raise CommandError("--count must be between 1 and 100.")
        if stock < 0:
            raise CommandError("--stock cannot be negative.")

        categories = self.get_categories()
        colors = self.get_colors()
        sizes = self.get_sizes()

        image_dir = self.resolve_image_dir(options["image_dir"])
        images = self.find_images(image_dir)[:count]
        if not images:
            raise CommandError(f"No supported images found in: {image_dir}")

        comment_user = None
        if options["with_comments"]:
            comment_user = (
                User.objects
                .filter(is_active=True, is_superuser=False)
                .order_by("id")
                .first()
            )
            if comment_user is None:
                raise CommandError(
                    "--with-comments requires at least one active non-superuser account."
                )

        created_count = 0
        updated_count = 0

        for index, image_path in enumerate(images, start=1):
            category_slug = self.category_for_index(index)
            category = categories[category_slug]

            name = self.product_name(image_path, index)
            slug = slugify(name, allow_unicode=True)

            price = self.price_for_index(index)

            product, created = Product.objects.update_or_create(
                slug=slug,
                defaults={
                    "category": category,
                    "name": name,
                    "short_description": (
                        "محصولی با طراحی مدرن و مناسب استفاده روزمره."
                    ),
                    "description": (
                        f"{name} از مجموعه BABAEI؛ محصولی با طراحی ساده و کاربردی "
                        "برای استایل روزمره و شخصی."
                    ),
                    "base_price": price,
                    "compare_at_price": price + 150000,
                    "is_active": True,
                    "is_featured": index <= 6,
                    "seo_title": f"{name} | BABAEI",
                    "seo_description": f"خرید {name} از فروشگاه BABAEI.",
                },
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

            self.sync_variants(product, colors, sizes, price, stock)
            self.sync_primary_image(product, image_path, name)

            if comment_user:
                self.seed_comments(product, comment_user)

            self.stdout.write(
                f"[{index}/{len(images)}] {'Created' if created else 'Updated'}: {name}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created_count} new, {updated_count} updated, "
                f"{len(images)} images/products processed."
            )
        )

    def resolve_image_dir(self, configured):
        base_dir = Path(settings.BASE_DIR)

        if configured:
            path = Path(configured)
            if not path.is_absolute():
                path = base_dir / path
        else:
            candidates = [
                base_dir / "static" / "images",
                base_dir / "config" / "static" / "images",
            ]
            path = next((candidate for candidate in candidates if candidate.is_dir()), candidates[0])

        if not path.is_dir():
            raise CommandError(f"Image directory not found: {path}")

        return path

    def find_images(self, root):
        excluded_parts = {"home", "back", "cards"}
        images = []

        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            relative_parts = path.relative_to(root).parts
            if any(part.lower() in excluded_parts for part in relative_parts[:-1]):
                continue
            if relative_parts[0].lower() == "shop" and path.stem.lower().startswith("hero-"):
                continue
            images.append(path)

        return sorted(images, key=lambda path: str(path).lower())

    def get_categories(self):
        categories = {category.slug: category for category in Category.objects.filter(is_active=True)}
        for sort_order, (name, slug) in enumerate(DEFAULT_CATEGORIES):
            category = categories.get(slug)
            if category is None:
                category = Category.objects.create(
                    name=name, slug=slug, description=f"محصولات {name} BABAEI.",
                    is_active=True, sort_order=sort_order,
                    seo_title=f"{name} | BABAEI", seo_description=f"خرید {name} از فروشگاه BABAEI.",
                )
                categories[slug] = category
        return categories

    def get_colors(self):
        colors = list(ProductColor.objects.filter(is_active=True, product__isnull=True).order_by("name"))
        if not colors:
            for name, slug, hex_code in DEFAULT_COLORS:
                ProductColor.objects.update_or_create(product=None, slug=slug, defaults={"name": name, "hex_code": hex_code, "is_active": True})
            colors = list(ProductColor.objects.filter(is_active=True, product__isnull=True).order_by("name"))
        return colors

    def get_sizes(self):
        sizes = list(ProductSize.objects.filter(is_active=True).order_by("sort_order", "name"))
        if not sizes:
            for name, slug, sort_order in DEFAULT_SIZES:
                ProductSize.objects.update_or_create(slug=slug, defaults={"name": name, "sort_order": sort_order, "is_active": True})
            sizes = list(ProductSize.objects.filter(is_active=True).order_by("sort_order", "name"))
        return sizes
    def category_for_index(self, index):
        category_order = [
            "t-shirts",
            "hoodies",
            "oversized",
            "accessories",
        ]
        return category_order[(index - 1) % len(category_order)]

    def product_name(self, image_path, index):
        stem = image_path.stem.replace("_", " ").replace("-", " ").strip()
        stem = " ".join(stem.split())

        # Avoid generic technical filenames such as 001 or image-12.
        if not stem or stem.lower().replace(" ", "").isdigit():
            return f"محصول BABAEI {index:02d}"

        return f"{PRODUCT_TEMPLATES[(index - 1) % len(PRODUCT_TEMPLATES)][0]} {stem}"

    def price_for_index(self, index):
        return 890000 + ((index - 1) % 10) * 100000

    def sync_variants(self, product, colors, sizes, price, stock):
        for color in colors:
            for size in sizes:
                ProductVariant.objects.update_or_create(
                    product=product,
                    color=color,
                    size=size,
                    defaults={
                        "sku": f"BAB-{product.pk}-{color.slug}-{size.slug}"[:80],
                        "use_product_price": True,
                        "price": price,
                        "compare_at_price": price + 150000,
                        "stock_quantity": stock,
                        "is_active": True,
                    },
                )

    def sync_primary_image(self, product, image_path, name):
        current = (
            ProductImage.objects
            .filter(
                product=product,
                image_type=ProductImage.ImageType.PRIMARY,
            )
            .order_by("id")
            .first()
        )

        # Do not replace an already uploaded product image on every run.
        if current and current.image and current.image.name:
            return

        with image_path.open("rb") as image_file:
            image = ProductImage(
                product=product,
                alt_text=name,
                image_type=ProductImage.ImageType.PRIMARY,
                sort_order=0,
            )
            image.image.save(image_path.name, File(image_file), save=True)

    def seed_comments(self, product, user):
        for body, rating in COMMENT_TEXTS:
            ProductComment.objects.get_or_create(
                product=product,
                user=user,
                body=body,
                defaults={
                    "rating": rating,
                    "status": ProductComment.Status.APPROVED,
                    "verified_purchase": False,
                },
            )
