from __future__ import annotations

from io import BytesIO

from django.core.files.base import ContentFile

from .models import ProductImage


DEFAULT_WIDTHS = (400, 640, 900)
FOREGROUND_FORMATS = (
    ("webp", "WEBP", {"quality": 78, "method": 6}),
    ("avif", "AVIF", {"quality": 60, "speed": 4}),
)


def generate_variants_for_product_image(
    image_id: int,
    *,
    widths=DEFAULT_WIDTHS,
    force: bool = False,
    dry_run: bool = False,
):
    """Generate responsive variants using Django's configured storage backend."""
    if not widths:
        return {"written": 0, "skipped": 0, "failed": 0}

    record = ProductImage.objects.get(pk=image_id)
    field = record.image
    if not field or not field.name:
        return {"written": 0, "skipped": 1, "failed": 0}

    try:
        with field.open("rb") as source:
            raw = source.read()
    except (OSError, ValueError) as exc:
        return {"written": 0, "skipped": 1, "failed": 1, "error": str(exc)}

    try:
        from PIL import Image, ImageOps

        with Image.open(BytesIO(raw)) as probe:
            probe = ImageOps.exif_transpose(probe)
            original_width, original_height = probe.size
            base = probe.convert("RGBA") if probe.mode in ("RGBA", "LA", "P") else probe.convert("RGB")
            base.load()
    except Exception as exc:
        return {"written": 0, "skipped": 1, "failed": 1, "error": str(exc)}

    written = 0
    skipped = 0
    failed = 0

    for width in sorted(set(int(item) for item in widths if int(item) > 0)):
        if width >= original_width:
            skipped += 1
            continue

        height = max(1, round(original_height * width / original_width))
        frame = base.resize((width, height), Image.Resampling.LANCZOS)

        for extension, image_format, save_kwargs in FOREGROUND_FORMATS:
            target_name = f"{field.name.rsplit('.', 1)[0]}-{width}.{extension}"

            try:
                exists = field.storage.exists(target_name)
                if exists and not force:
                    skipped += 1
                    continue

                if dry_run:
                    skipped += 1
                    continue

                output = BytesIO()
                frame.save(output, image_format, **save_kwargs)
                output.seek(0)
                field.storage.save(target_name, ContentFile(output.getvalue()))
                written += 1
            except Exception as exc:
                failed += 1
                try:
                    field.storage.delete(target_name)
                except Exception:
                    pass

    return {"written": written, "skipped": skipped, "failed": failed}
