from __future__ import annotations

from pathlib import Path

from django.contrib.staticfiles import finders
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.customizer.models import Artwork


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class Command(BaseCommand):
    help = "Import every image in static/images/customizer/labels/ into the permanent label library."

    @transaction.atomic
    def handle(self, *args, **options):
        root = finders.find("images/customizer/labels")
        if not root:
            raise CommandError(
                "Label directory not found: static/images/customizer/labels/"
            )

        root = Path(root)
        if not root.is_dir():
            raise CommandError(f"Label directory is not a directory: {root}")

        files = sorted(
            path for path in root.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )

        if not files:
            raise CommandError(
                f"No supported label images found in: {root}. "
                "Expected PNG/JPG/JPEG/WEBP files."
            )

        created = 0
        updated = 0

        for path in files:
            name = self.label_name(path)
            slug = slugify(path.stem, allow_unicode=True) or path.stem.lower()

            artwork, was_created = Artwork.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "source": Artwork.Source.LIBRARY,
                    "processing_status": Artwork.ProcessingStatus.READY,
                    "background_removed": True,
                    "base_price": 100000,
                    "min_width_px": 500,
                    "is_active": True,
                },
            )

            artwork.name = name
            artwork.source = Artwork.Source.LIBRARY
            artwork.processing_status = Artwork.ProcessingStatus.READY
            artwork.background_removed = True
            artwork.base_price = 100000
            artwork.min_width_px = 500
            artwork.is_active = True

            if not artwork.image or not artwork.image.name:
                with path.open("rb") as image_file:
                    artwork.image.save(path.name, File(image_file), save=False)

            artwork.save()

            if was_created:
                created += 1
                action = "Created"
            else:
                updated += 1
                action = "Updated"

            self.stdout.write(f"{action} label: {name} ({path.name})")

        self.stdout.write(self.style.SUCCESS(
            f"Label library ready: {created} created, {updated} updated, "
            f"{len(files)} image(s) processed."
        ))

    @staticmethod
    def label_name(path):
        return " ".join(
            part.capitalize()
            for part in path.stem.replace("_", " ").replace("-", " ").split()
        )
