from io import BytesIO

from django.core.files.base import ContentFile
from django.db import migrations
from django.utils.text import slugify


def create_demo_designer_setup(apps, schema_editor):
    Product = apps.get_model("shop", "Product")
    ProductImage = apps.get_model("shop", "ProductImage")
    DesignerView = apps.get_model("customizer", "DesignerView")
    PrintArea = apps.get_model("customizer", "PrintArea")
    PrintAreaView = apps.get_model("customizer", "PrintAreaView")
    Artwork = apps.get_model("customizer", "Artwork")

    product = Product.objects.filter(is_active=True).order_by("id").first()
    if not product:
        return

    product_image = (
        ProductImage.objects.filter(product=product)
        .order_by("sort_order", "id")
        .first()
    )
    if not product_image:
        return

    designer_view, _ = DesignerView.objects.get_or_create(
        product=product,
        key="front",
        defaults={
            "name": "نمای جلو",
            "background_image": product_image.image.name,
            "canvas_width": 1600,
            "canvas_height": 1600,
            "angle": 0,
            "sort_order": 0,
            "is_active": True,
        },
    )

    # A development-ready default chest print zone. The geometry is normalized
    # to the designer canvas and can be replaced from the admin later.
    area, _ = PrintArea.objects.get_or_create(
        product=product,
        key="left_chest",
        defaults={
            "name": "سینه چپ",
            "max_width_mm": 110,
            "max_height_mm": 110,
            "max_layers": 3,
            "sort_order": 0,
            "is_active": True,
        },
    )

    PrintAreaView.objects.get_or_create(
        area=area,
        view=designer_view,
        defaults={
            "geometry": [
                {"x": 0.43, "y": 0.27},
                {"x": 0.57, "y": 0.27},
                {"x": 0.57, "y": 0.39},
                {"x": 0.43, "y": 0.39},
            ]
        },
    )

    # Add a small transparent demo artwork so the designer is immediately
    # usable in a fresh development database. Real artwork can be managed from
    # the admin and this record can be disabled/deleted there.
    artwork_slug = "demo-babaei-label"
    artwork, created = Artwork.objects.get_or_create(
        slug=artwork_slug,
        defaults={
            "name": "لیبل نمونه BABAEI",
            "source": "library",
            "processing_status": "ready",
            "background_removed": True,
            "base_price": 100000,
            "min_width_px": 300,
            "is_active": True,
        },
    )
    if created or not artwork.image:
        try:
            from PIL import Image, ImageDraw

            image = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((70, 70, 530, 530), radius=60, fill=(18, 18, 18, 255))
            draw.text((148, 278), "BABAEI", fill=(220, 190, 100, 255))
            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            artwork.image.save("demo-babaei-label.png", ContentFile(buffer.getvalue()), save=True)
        except Exception:
            if created:
                artwork.delete()
            return


def remove_demo_designer_setup(apps, schema_editor):
    Artwork = apps.get_model("customizer", "Artwork")
    Artwork.objects.filter(slug="demo-babaei-label").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("customizer", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_demo_designer_setup, remove_demo_designer_setup),
    ]
