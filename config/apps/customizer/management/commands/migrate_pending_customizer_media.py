from pathlib import Path

from django.core.management.base import BaseCommand
from apps.customizer.models import Artwork, DesignDraft
from apps.customizer.services import save_bytes_to_temp
from apps.customizer.temp_storage import delete_customizer_temp_file
from apps.orders.models import Order, OrderItem


class Command(BaseCommand):
    help = (
        "Move legacy unpaid customizer uploads and previews from MEDIA_ROOT "
        "to private temporary storage."
    )

    def handle(self, *args, **options):
        paid_design_ids = set(
            OrderItem.objects.filter(
                order__payment_status=Order.PaymentStatus.PAID,
                custom_design_id__isnull=False,
            ).values_list("custom_design_id", flat=True)
        )

        paid_artwork_ids = set(
            OrderItem.objects.filter(
                order__payment_status=Order.PaymentStatus.PAID,
                custom_design__layers__artwork__source=Artwork.Source.UPLOAD,
            )
            .values_list("custom_design__layers__artwork_id", flat=True)
            .distinct()
        )

        migrated_artworks = 0
        migrated_previews = 0

        artworks = (
            Artwork.objects
            .filter(
                source=Artwork.Source.UPLOAD,
                image__isnull=False,
            )
            .exclude(id__in=paid_artwork_ids)
            .iterator(chunk_size=100)
        )
        for artwork in artworks:
            if not artwork.image or not artwork.image.name:
                continue

            with artwork.image.open("rb") as source:
                data = source.read()

            temp_path = save_bytes_to_temp(
                data,
                directory=f"artworks/{artwork.uuid}",
                filename=Path(artwork.image.name).name,
            )
            artwork.image.delete(save=False)
            old_temp = artwork.temp_image_path
            artwork.temp_image_path = temp_path
            artwork.save(update_fields=["image", "temp_image_path", "updated_at"])
            if old_temp:
                delete_customizer_temp_file(old_temp)
            migrated_artworks += 1

        previews = (
            DesignDraft.objects
            .exclude(id__in=paid_design_ids)
            .iterator(chunk_size=100)
        )
        for draft in previews:
            changed = []

            for side in ("front", "back"):
                media_field = getattr(draft, f"preview_{side}")
                if not media_field or not media_field.name:
                    continue

                with media_field.open("rb") as source:
                    data = source.read()

                temp_path = save_bytes_to_temp(
                    data,
                    directory=f"designs/{draft.uuid}/previews",
                    filename=Path(media_field.name).name,
                )
                media_field.delete(save=False)
                old_temp = getattr(draft, f"temp_preview_{side}_path")
                setattr(draft, f"temp_preview_{side}_path", temp_path)
                if old_temp:
                    delete_customizer_temp_file(old_temp)
                changed.extend(
                    [f"preview_{side}", f"temp_preview_{side}_path"]
                )
                migrated_previews += 1

            if changed:
                draft.save(update_fields=[*changed, "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Migrated legacy pending assets: "
                f"{migrated_artworks} artwork(s), {migrated_previews} preview(s)."
            )
        )
