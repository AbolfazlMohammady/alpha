"""Generate responsive product image derivatives.

New product-image saves are handled asynchronously by Celery. This management
command remains available for backfills, repairs, --force rebuilds and dry runs.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.shop.image_variants import DEFAULT_WIDTHS, generate_variants_for_product_image
from apps.shop.models import ProductImage


class Command(BaseCommand):
    help = "Generate AVIF/WebP derivatives for product card images."

    def add_arguments(self, parser):
        parser.add_argument(
            "--widths",
            default=",".join(
                str(width)
                for width in getattr(settings, "CARD_IMAGE_WIDTHS", DEFAULT_WIDTHS)
            ),
            help="Comma separated target widths (default: %(default)s).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Rebuild derivatives that already exist.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be written, change nothing.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Stop after N images (0 = no limit).",
        )

    def handle(self, *args, **options):
        widths = sorted(
            {
                int(item)
                for item in str(options["widths"]).split(",")
                if item.strip()
            }
        )
        force = options["force"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        image_ids = ProductImage.objects.exclude(image="").values_list("id", flat=True).iterator()

        written = skipped = failed = 0
        for index, image_id in enumerate(image_ids, start=1):
            if limit and index > limit:
                break

            result = generate_variants_for_product_image(
                image_id,
                widths=widths,
                force=force,
                dry_run=dry_run,
            )
            written += result["written"]
            skipped += result["skipped"]
            failed += result["failed"]

            if result.get("error"):
                self.stdout.write(
                    self.style.ERROR(
                        f"failed image {image_id}: {result['error']}"
                    )
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"written {written}, skipped {skipped}, failed {failed}"
            )
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("dry run: nothing was written"))
