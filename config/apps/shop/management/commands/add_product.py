from __future__ import annotations

from pathlib import Path

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


class Command(BaseCommand):
    """
    Add or update one real catalog product from the command line.

    The command intentionally uses the ProductSize rows already configured
    in the system. It never invents a fixed S/M/L/XL list.
    """

    help = "Add or update one BABAEI product with variants and an optional comment."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Product name.")
        parser.add_argument("--category", required=True, help="Existing category slug.")
        parser.add_argument("--price", required=True, type=int, help="Base price in toman.")
        parser.add_argument("--compare-at-price", type=int, default=None)
        parser.add_argument("--short-description", default="")
        parser.add_argument("--description", default="")
        parser.add_argument("--featured", action="store_true")
        parser.add_argument(
            "--image",
            type=str,
            default="",
            help="Optional local path to the primary product image.",
        )
        parser.add_argument(
            "--stock",
            type=int,
            default=12,
            help="Initial stock for every active color/size variant.",
        )
        parser.add_argument(
            "--comment",
            default="",
            help="Optional initial product comment.",
        )
        parser.add_argument("--rating", type=int, choices=range(1, 6), default=None)
        parser.add_argument(
            "--comment-user-phone",
            default="",
            help="Existing customer phone used for the optional comment.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        name = options["name"].strip()
        if not name:
            raise CommandError("--name cannot be empty.")
        if options["price"] < 0:
            raise CommandError("--price cannot be negative.")
        if options["compare_at_price"] is not None and options["compare_at_price"] < options["price"]:
            raise CommandError("--compare-at-price must be greater than or equal to --price.")
        if options["stock"] < 0:
            raise CommandError("--stock cannot be negative.")

        category = Category.objects.filter(
            slug=options["category"].strip(),
            is_active=True,
        ).first()
        if category is None:
            raise CommandError("Active category not found.")

        sizes = list(
            ProductSize.objects.filter(is_active=True).order_by("sort_order", "name")
        )
        colors = list(
            ProductColor.objects.filter(is_active=True, product__isnull=True)
            .order_by("name")
        )

        if not sizes:
            raise CommandError(
                "No active ProductSize exists. Add sizes in the Control Center first."
            )
        if not colors:
            raise CommandError(
                "No active global ProductColor exists. Add colors before creating a product."
            )

        slug = slugify(name, allow_unicode=True)
        product, created = Product.objects.update_or_create(
            slug=slug,
            defaults={
                "category": category,
                "name": name,
                "short_description": options["short_description"].strip(),
                "description": options["description"].strip(),
                "base_price": options["price"],
                "compare_at_price": options["compare_at_price"],
                "is_active": True,
                "is_featured": options["featured"],
                "seo_title": f"{name} | BABAEI",
                "seo_description": f"خرید {name} از فروشگاه BABAEI.",
            },
        )

        # Keep variants synchronized with the currently configured sizes/colors.
        for color in colors:
            for size in sizes:
                sku = f"BAB-{product.pk}-{color.slug}-{size.slug}"[:80]
                ProductVariant.objects.update_or_create(
                    product=product,
                    color=color,
                    size=size,
                    defaults={
                        "sku": sku,
                        "use_product_price": True,
                        "price": options["price"],
                        "compare_at_price": options["compare_at_price"],
                        "stock_quantity": options["stock"],
                        "is_active": True,
                    },
                )

        image_path = options["image"].strip()
        if image_path:
            source = Path(image_path)
            if not source.is_file():
                raise CommandError(f"Image file not found: {source}")
            ProductImage.objects.filter(
                product=product,
                image_type=ProductImage.ImageType.PRIMARY,
            ).delete()
            with source.open("rb") as image_file:
                product_image = ProductImage(
                    product=product,
                    alt_text=name,
                    image_type=ProductImage.ImageType.PRIMARY,
                    sort_order=0,
                )
                product_image.image.save(source.name, File(image_file), save=True)

        comment = options["comment"].strip()
        if comment:
            phone = options["comment-user-phone"].strip()
            user_qs = User.objects.filter(is_active=True, is_superuser=False)
            if phone:
                user_qs = user_qs.filter(phone=phone)
            user = user_qs.order_by("id").first()
            if user is None:
                raise CommandError(
                    "An active non-superuser customer is required for --comment."
                )

            ProductComment.objects.get_or_create(
                product=product,
                user=user,
                body=comment,
                defaults={
                    "rating": options["rating"],
                    "status": ProductComment.Status.PENDING,
                    "verified_purchase": False,
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} product '{product.name}' "
                f"(id={product.pk}) with {len(colors) * len(sizes)} variants."
            )
        )
