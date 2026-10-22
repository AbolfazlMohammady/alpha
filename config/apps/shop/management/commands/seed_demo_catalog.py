from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from django.core.files import File
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.contrib.staticfiles import finders
from django.utils.text import slugify

from apps.shop.models import Category, Product, ProductColor, ProductComment, ProductImage, ProductSize, ProductVariant
from apps.users.models import User


# Free-to-use Unsplash images. The command downloads a local copy into MEDIA_ROOT,
# so the storefront does not depend on a remote image URL at runtime.
IMAGE_URLS = [
    "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?auto=format&fit=crop&w=1200&q=72",
    "https://images.unsplash.com/photo-1618354691373-d851c5c3a990?auto=format&fit=crop&w=1200&q=72",
    "https://images.unsplash.com/photo-1610502778270-c5c6f4c7d575?auto=format&fit=crop&w=1200&q=72",
    "https://images.unsplash.com/photo-1622586027597-c214d0f6db39?auto=format&fit=crop&w=1200&q=72",
    "https://images.unsplash.com/photo-1591047139829-d91aecb6caea?auto=format&fit=crop&w=1200&q=72",
    "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?auto=format&fit=crop&w=1200&q=72",
    "https://images.unsplash.com/photo-1503342217505-b0a15ec3261c?auto=format&fit=crop&w=1200&q=72",
    "https://images.unsplash.com/photo-1490481651871-ab68de25d43d?auto=format&fit=crop&w=1200&q=72",
    "https://images.unsplash.com/photo-1551028719-00167b16eac5?auto=format&fit=crop&w=1200&q=72",
    "https://images.unsplash.com/photo-1529139574466-a303027c1d8b?auto=format&fit=crop&w=1200&q=72",
    "https://images.unsplash.com/photo-1525507119028-ed4c629a60a3?auto=format&fit=crop&w=1200&q=72",
    "https://images.unsplash.com/photo-1469334031218-e382a71b716b?auto=format&fit=crop&w=1200&q=72",
]

CATEGORIES = [
    {
        "name": "تیشرت",
        "slug": "t-shirts",
        "image": "Tshirt.png",
        "description": "تیشرت‌های مینیمال و قابل شخصی‌سازی BABAEI.",
    },
    {
        "name": "هودی",
        "slug": "hoodies",
        "image": "Hoodis.png",
        "description": "هودی‌های راحت برای استایل روزمره و خیابانی.",
    },
    {
        "name": "اکسسوری",
        "slug": "accessories",
        "image": "accsory.png",
        "description": "اکسسوری‌های ساده برای کامل کردن استایل.",
    },
    {
        "name": "اورسایز",
        "slug": "oversized",
        "image": "Oversize.png",
        "description": "فیت‌های آزاد و اورسایز با حال‌وهوای مدرن.",
    },
]

PRODUCTS = [
    ("تیشرت Essential مشکی", "t-shirts", 890000, True),
    ("تیشرت Essential سفید", "t-shirts", 890000, True),
    ("تیشرت Graphic Shadow", "t-shirts", 1090000, True),
    ("تیشرت Mono Grey", "t-shirts", 950000, False),
    ("تیشرت Studio Cream", "t-shirts", 990000, True),
    ("هودی Core Black", "hoodies", 1890000, True),
    ("هودی Heavy Grey", "hoodies", 1990000, False),
    ("هودی Midnight", "hoodies", 2190000, True),
    ("هودی Sand Oversize", "hoodies", 2090000, False),
    ("هودی Signature", "hoodies", 2290000, True),
    ("اورسایز Boxy Black", "oversized", 1190000, True),
    ("اورسایز Washed Grey", "oversized", 1290000, False),
    ("اورسایز Off White", "oversized", 1250000, False),
    ("اورسایز Street Brown", "oversized", 1390000, True),
    ("اورسایز Minimal", "oversized", 1190000, False),
    ("کلاه BABAEI Classic", "accessories", 590000, False),
    ("کیف Crossbody Black", "accessories", 990000, True),
    ("جوراب Signature", "accessories", 290000, False),
    ("کیف Tote Everyday", "accessories", 790000, False),
    ("کپ Everyday", "accessories", 550000, False),
    ("تیشرت Urban Black", "t-shirts", 990000, False),
    ("هودی Urban Cream", "hoodies", 2090000, True),
    ("اورسایز Carbon", "oversized", 1350000, False),
    ("کیف Shoulder Mini", "accessories", 850000, False),
    ("تیشرت Heavy Cotton", "t-shirts", 1150000, True),
]

COLORS = [
    ("مشکی", "black", "#111111"),
    ("سفید", "white", "#F5F5F2"),
    ("طوسی", "gray", "#8A8A86"),
]

SIZES = [
    ("S", "s", 1),
    ("M", "m", 2),
    ("L", "l", 3),
    ("XL", "xl", 4),
]

# Optional demo comments. They are only created when --with-comments is used.
DEMO_COMMENTS = [
    ("کیفیت محصول خیلی خوبه و دوختش تمیزه.", 5),
    ("رنگ و فرم محصول دقیقاً مطابق توضیحات بود.", 5),
    ("برای استفاده روزمره انتخاب خیلی خوبیه.", 4),
]


class Command(BaseCommand):
    help = "Populate BABAEI with demo categories, products, variants and local product images."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Number of demo products to create (default: 20).",
        )
        parser.add_argument(
            "--skip-download",
            action="store_true",
            help="Create catalog data without downloading remote product images.",
        )
        parser.add_argument(
            "--with-comments",
            action="store_true",
            help="Add a small set of demo comments to the seeded products using an existing customer account.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1 or limit > len(PRODUCTS):
            raise CommandError(f"--limit must be between 1 and {len(PRODUCTS)}")

        categories = self.seed_categories()
        colors = self.seed_colors()
        sizes = self.seed_sizes()
        comment_user = self.get_comment_user() if options["with_comments"] else None
        downloaded = 0
        created_products = 0

        for index, (name, category_slug, price, featured) in enumerate(PRODUCTS[:limit], start=1):
            category = categories[category_slug]
            product, created = Product.objects.update_or_create(
                slug=slugify(name, allow_unicode=True),
                defaults={
                    "category": category,
                    "name": name,
                    "short_description": "محصولی با طراحی مینیمال و کیفیت مناسب برای استفاده روزمره.",
                    "description": (
                        f"{name} از مجموعه BABAEI؛ طراحی ساده، قابل استفاده روزمره و مناسب برای استایل شخصی. "
                        "در مرحله طراحی اختصاصی می‌توانی چاپ و جزئیات دلخواهت را به محصول اضافه کنی."
                    ),
                    "base_price": price,
                    "is_active": True,
                    "is_featured": featured,
                    "seo_title": f"{name} | BABAEI",
                    "seo_description": f"خرید {name} از BABAEI با کیفیت بالا و امکان طراحی اختصاصی.",
                },
            )
            created_products += int(created)

            self.seed_variants(product, colors, sizes, price, index)

            if comment_user:
                self.seed_comments(product, comment_user)

            if not ProductImage.objects.filter(
                product=product,
                image_type=ProductImage.ImageType.PRIMARY,
            ).exists():
                if not options["skip_download"]:
                    image = self.download_product_image(product, index - 1, name)
                    downloaded += int(image)

        self.stdout.write(self.style.SUCCESS(
            f"BABAEI demo catalog ready: {len(categories)} categories, "
            f"{limit} products ({created_products} new), "
            f"{len(colors) * len(sizes) * limit} variants, {downloaded} images downloaded."
        ))
        self.stdout.write("Homepage category images were restored from config/static/images/home/.")

    def seed_categories(self):
        result = {}
        for item in CATEGORIES:
            category, _ = Category.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "is_active": True,
                    "sort_order": CATEGORIES.index(item),
                    "seo_title": f"{item['name']} | BABAEI",
                    "seo_description": f"خرید {item['name']} از فروشگاه BABAEI.",
                },
            )
            self.restore_category_image(category, item["image"])
            result[category.slug] = category
        return result

    def restore_category_image(self, category, filename):
        if category.image and category.image.name:
            return
        source = finders.find(f"images/home/{filename}")
        if not source or not Path(source).is_file():
            self.stdout.write(self.style.WARNING(f"Category image not found: {filename}"))
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
        """
        Use sizes already configured in the system.

        The old seeder always created S/M/L/XL, which made the catalog
        disagree with the Control Center. If no active sizes exist yet,
        create the original demo defaults once.
        """
        active_sizes = list(
            ProductSize.objects.filter(is_active=True).order_by("sort_order", "name")
        )
        if not active_sizes:
            for name, slug, sort_order in SIZES:
                ProductSize.objects.update_or_create(
                    slug=slug,
                    defaults={
                        "name": name,
                        "sort_order": sort_order,
                        "is_active": True,
                    },
                )
            active_sizes = list(
                ProductSize.objects.filter(is_active=True).order_by("sort_order", "name")
            )
        return {size.slug: size for size in active_sizes}

    def get_comment_user(self):
        user = (
            User.objects
            .filter(is_active=True, is_superuser=False)
            .order_by("id")
            .first()
        )
        if user is None:
            raise CommandError(
                "--with-comments requires at least one active non-superuser account."
            )
        return user

    def seed_comments(self, product, user):
        for body, rating in DEMO_COMMENTS:
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

    def seed_variants(self, product, colors, sizes, price, product_number):
        price_by_color = {
            "black": price,
            "white": price,
            "gray": price + 50000,
        }
        for color_slug, color in colors.items():
            for size_slug, size in sizes.items():
                ProductVariant.objects.update_or_create(
                    product=product,
                    color=color,
                    size=size,
                    defaults={
                        "sku": f"BAB-{product_number:02d}-{color_slug[:3].upper()}-{size_slug.upper()}",
                        "price": price_by_color[color_slug],
                        "use_product_price": False,
                        "stock_quantity": 12,
                        "is_active": True,
                    },
                )

    def download_product_image(self, product, image_index, product_name):
        url = IMAGE_URLS[image_index % len(IMAGE_URLS)]
        try:
            request = Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (BABAEI demo catalog seeder)"},
            )
            with urlopen(request, timeout=20) as response:
                data = response.read()
                content_type = response.headers.get("Content-Type", "")

            if not data or not content_type.startswith("image/"):
                raise ValueError("remote response is not an image")

            extension = ".jpg"
            if "png" in content_type:
                extension = ".png"
            elif "webp" in content_type:
                extension = ".webp"

            filename = f"{slugify(product_name, allow_unicode=True)}{extension}"
            ProductImage.objects.create(
                product=product,
                image=ContentFile(data, name=filename),
                alt_text=product_name,
                image_type=ProductImage.ImageType.PRIMARY,
                sort_order=0,
            )
            return True
        except Exception as exc:
            self.stdout.write(self.style.WARNING(
                f"Image download failed for '{product_name}': {exc}"
            ))
            return False
