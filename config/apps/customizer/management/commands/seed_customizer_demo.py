from __future__ import annotations

from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand
from django.contrib.staticfiles import finders
from django.db import transaction
from django.utils.text import slugify

from apps.shop.models import Product, ProductImage

from apps.customizer.models import Artwork, ArtworkAreaPrice, DesignerView, PrintArea, PrintAreaView


LABELS = [
    ("BABAEI Wordmark", "babaei-wordmark.png", 100000),
    ("Lightning Badge", "lightning-badge.png", 120000),
    ("Crown Label", "crown.png", 140000),
]


class Command(BaseCommand):
    help = "Prepare existing BABAEI products for the customizer and add demo transparent labels."

    def handle(self, *args, **options):
        products = Product.objects.filter(is_active=True).order_by("id")
        prepared = 0
        skipped = 0

        with transaction.atomic():
            artworks = self.seed_artworks()
            for product in products:
                primary = ProductImage.objects.filter(
                    product=product,
                    image_type=ProductImage.ImageType.PRIMARY,
                ).first()
                if not primary:
                    skipped += 1
                    continue
                self.seed_product_designer(product, primary)
                self.seed_prices(product, artworks)
                prepared += 1

        self.stdout.write(self.style.SUCCESS(
            f"Customizer demo ready: {prepared} products prepared, {len(artworks)} labels available, {skipped} products skipped."
        ))
        self.stdout.write("Open /customizer/design/<product-slug>/ to test the designer.")

    def seed_product_designer(self, product, primary):
        view, _ = DesignerView.objects.update_or_create(
            product=product,
            key="front",
            defaults={
                "name": "نمای جلو",
                "background_image": primary.image.name,
                "canvas_width": 1600,
                "canvas_height": 1600,
                "angle": 0,
                "sort_order": 0,
                "is_active": True,
            },
        )

        areas = [
            {
                "key": "left-chest",
                "name": "سینه چپ",
                "geometry": [
                    {"x": 0.34, "y": 0.28},
                    {"x": 0.52, "y": 0.28},
                    {"x": 0.52, "y": 0.43},
                    {"x": 0.34, "y": 0.43},
                ],
                "max_width_mm": 100,
                "max_height_mm": 100,
                "sort_order": 0,
            },
            {
                "key": "center-chest",
                "name": "مرکز جلو",
                "geometry": [
                    {"x": 0.36, "y": 0.40},
                    {"x": 0.64, "y": 0.40},
                    {"x": 0.64, "y": 0.66},
                    {"x": 0.36, "y": 0.66},
                ],
                "max_width_mm": 280,
                "max_height_mm": 320,
                "sort_order": 1,
            },
            {
                "key": "left-sleeve",
                "name": "آستین چپ",
                "geometry": [
                    {"x": 0.16, "y": 0.35},
                    {"x": 0.30, "y": 0.35},
                    {"x": 0.30, "y": 0.61},
                    {"x": 0.16, "y": 0.61},
                ],
                "max_width_mm": 90,
                "max_height_mm": 180,
                "sort_order": 2,
            },
        ]

        for item in areas:
            area, _ = PrintArea.objects.update_or_create(
                product=product,
                key=item["key"],
                defaults={
                    "name": item["name"],
                    "max_width_mm": item["max_width_mm"],
                    "max_height_mm": item["max_height_mm"],
                    "max_layers": 3,
                    "sort_order": item["sort_order"],
                    "is_active": True,
                },
            )
            PrintAreaView.objects.update_or_create(
                area=area,
                view=view,
                defaults={"geometry": item["geometry"]},
            )

    def seed_artworks(self):
        result = []
        for name, filename, price in LABELS:
            slug = slugify(name, allow_unicode=True)
            artwork, created = Artwork.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "source": Artwork.Source.LIBRARY,
                    "processing_status": Artwork.ProcessingStatus.READY,
                    "background_removed": True,
                    "base_price": price,
                    "min_width_px": 500,
                    "is_active": True,
                },
            )
            if created or not artwork.image:
                source = finders.find(f"images/customizer/labels/{filename}")
                if source and Path(source).is_file():
                    with open(source, "rb") as image_file:
                        artwork.image.save(filename, File(image_file), save=True)
                elif not artwork.image:
                    self.stdout.write(self.style.WARNING(f"Label asset not found: {filename}"))
            if artwork.image:
                result.append(artwork)
        return result

    def seed_prices(self, product, artworks):
        areas = list(PrintArea.objects.filter(product=product, is_active=True))
        for artwork in artworks:
            for area in areas:
                multiplier = {"left-chest": 1, "center-chest": 1.25, "left-sleeve": 1.15}.get(area.key, 1)
                price = int(artwork.base_price * multiplier)
                ArtworkAreaPrice.objects.update_or_create(
                    artwork=artwork,
                    area=area,
                    defaults={"price": price},
                )
