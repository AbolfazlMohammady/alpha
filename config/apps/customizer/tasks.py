from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path, PurePosixPath

from celery import shared_task
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import Artwork, DesignDraft, Product3DAsset
from .product_3d import prepare_product_asset, refresh_product_asset
from .services import remove_background
from .temp_storage import delete_customizer_temp_file, resolve_customizer_temp_path, get_customizer_temp_root, save_bytes_to_temp
from apps.file_cleanup import derivative_names
from apps.orders.models import CartItem, OrderItem


def _mark_artwork_failed(artwork_id: int, message: str) -> None:
    Artwork.objects.filter(id=artwork_id).update(
        processing_status=Artwork.ProcessingStatus.FAILED,
        background_removed=False,
        updated_at=timezone.now(),
    )


def _mark_asset_failed(asset_id: int, message: str) -> None:
    Product3DAsset.objects.filter(id=asset_id).update(
        status=Product3DAsset.Status.FAILED,
        error_message=message[:2000],
    )


@shared_task(bind=True, max_retries=2, default_retry_delay=20, acks_late=True)
def process_uploaded_artwork(self, artwork_id):
    """Run the expensive local background-removal model outside Django HTTP workers."""
    try:
        artwork = Artwork.objects.get(
            id=artwork_id,
            source=Artwork.Source.UPLOAD,
        )
    except Artwork.DoesNotExist:
        return {"status": "missing"}

    if artwork.processing_status == Artwork.ProcessingStatus.READY:
        return {"status": artwork.processing_status, "artwork_id": artwork.id}

    if artwork.processing_status != Artwork.ProcessingStatus.PROCESSING:
        return {"status": artwork.processing_status, "artwork_id": artwork.id}

    new_name = f"{artwork.uuid}.png"
    try:
        if not artwork.temp_image_path:
            raise ValidationError("فایل موقت تصویر پیدا نشد.")

        temp_path = resolve_customizer_temp_path(artwork.temp_image_path)
        if not temp_path.is_file():
            raise ValidationError("فایل موقت تصویر دیگر وجود ندارد.")

        with temp_path.open("rb") as source:
            processed = remove_background(source)

        old_temp_path = artwork.temp_image_path
        new_temp_path = save_bytes_to_temp(
            processed,
            directory=f"artworks/{artwork.uuid}",
            filename=new_name,
        )
        artwork.temp_image_path = new_temp_path
        artwork.processing_status = Artwork.ProcessingStatus.READY
        artwork.background_removed = True
        artwork.save(
            update_fields=[
                "temp_image_path",
                "processing_status",
                "background_removed",
                "updated_at",
            ]
        )
        delete_customizer_temp_file(old_temp_path)
        return {"status": artwork.processing_status, "artwork_id": artwork.id}
    except ValidationError as exc:
        _mark_artwork_failed(artwork_id, str(exc))
        return {"status": "failed", "artwork_id": artwork_id, "error": str(exc)}
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            _mark_artwork_failed(
                artwork_id,
                "پردازش تصویر با خطای غیرمنتظره متوقف شد.",
            )
            return {
                "status": "failed",
                "artwork_id": artwork_id,
                "error": "processing failed",
            }
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=20, acks_late=True)
def prepare_product_3d(self, asset_id):
    try:
        asset = Product3DAsset.objects.select_related("product").get(id=asset_id)
        if asset.status == Product3DAsset.Status.READY:
            return {"status": asset.status}

        if asset.status == Product3DAsset.Status.GENERATING and asset.task_id:
            poll_product_3d.apply_async(args=[asset.id], countdown=5)
            return {"status": asset.status, "task_id": asset.task_id}

        prepare_product_asset(asset)

        if asset.status == Product3DAsset.Status.GENERATING and asset.task_id:
            poll_product_3d.apply_async(args=[asset.id], countdown=5)

        return {"status": asset.status, "task_id": asset.task_id}
    except Product3DAsset.DoesNotExist:
        return {"status": "missing"}
    except ValidationError as exc:
        _mark_asset_failed(asset_id, str(exc))
        return {"status": "failed", "error": str(exc)}
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            _mark_asset_failed(
                asset_id,
                "پردازش مدل سه‌بعدی با خطای غیرمنتظره متوقف شد.",
            )
            return {"status": "failed", "error": "processing failed"}
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=120, default_retry_delay=10, acks_late=True)
def poll_product_3d(self, asset_id):
    """Poll Meshy from a worker so browser requests never call the external API."""
    try:
        asset = Product3DAsset.objects.select_related("product").get(id=asset_id)
    except Product3DAsset.DoesNotExist:
        return {"status": "missing"}

    if asset.status in {
        Product3DAsset.Status.READY,
        Product3DAsset.Status.FAILED,
    }:
        return {"status": asset.status}

    if not asset.task_id:
        return {"status": asset.status, "waiting": True}

    try:
        refresh_product_asset(asset)
    except ValidationError as exc:
        if self.request.retries >= 5:
            _mark_asset_failed(asset_id, str(exc))
            return {"status": "failed", "error": str(exc)}
        raise self.retry(exc=exc, countdown=min(30, 5 + self.request.retries * 5))
    except Exception as exc:
        if self.request.retries >= 5:
            _mark_asset_failed(
                asset_id,
                "ارتباط با سرویس ساخت مدل سه‌بعدی پایدار نبود.",
            )
            return {"status": "failed", "error": "provider unavailable"}
        raise self.retry(exc=exc, countdown=min(30, 5 + self.request.retries * 5))

    if asset.status == Product3DAsset.Status.GENERATING:
        if self.request.retries >= self.max_retries:
            _mark_asset_failed(
                asset_id,
                "ساخت مدل سه‌بعدی در مهلت مجاز کامل نشد.",
            )
            return {"status": "failed", "error": "provider timeout"}
        raise self.retry(countdown=10)

    return {"status": asset.status, "progress": asset.progress}



@shared_task
def cleanup_stale_uploaded_artworks():
    """Remove customer uploads that were never attached to a retained design."""
    cutoff = timezone.now() - timedelta(hours=48)
    stale_ids = list(
        Artwork.objects.filter(
            source=Artwork.Source.UPLOAD,
            processing_status__in=[
                Artwork.ProcessingStatus.READY,
                Artwork.ProcessingStatus.FAILED,
                Artwork.ProcessingStatus.PROCESSING,
            ],
            updated_at__lt=cutoff,
            design_layers__isnull=True,
        ).values_list("id", flat=True)[:500]
    )
    if not stale_ids:
        return {"deleted": 0}
    deleted, _ = Artwork.objects.filter(id__in=stale_ids).delete()
    return {"deleted": deleted}


@shared_task
def cleanup_stale_design_drafts():
    """Delete old drafts that are no longer referenced by cart or orders."""
    cutoff = timezone.now() - timedelta(days=7)
    protected_cart_ids = CartItem.objects.filter(
        custom_design_id__isnull=False
    ).values_list("custom_design_id", flat=True)
    protected_order_ids = OrderItem.objects.filter(
        custom_design_id__isnull=False
    ).values_list("custom_design_id", flat=True)

    stale_ids = list(
        DesignDraft.objects.filter(
            status__in=[
                DesignDraft.Status.DRAFT,
                DesignDraft.Status.CART,
                DesignDraft.Status.EXPIRED,
            ],
            updated_at__lt=cutoff,
        )
        .exclude(id__in=protected_cart_ids)
        .exclude(id__in=protected_order_ids)
        .values_list("id", flat=True)[:200]
    )
    if not stale_ids:
        return {"deleted": 0}
    deleted, _ = DesignDraft.objects.filter(id__in=stale_ids).delete()
    return {"deleted": deleted}


@shared_task
def cleanup_orphan_customizer_temp_files():
    """Remove temporary customizer files no longer referenced by DB."""
    root = get_customizer_temp_root()
    if not root.exists():
        return {"deleted": 0, "bytes": 0}

    referenced = set(
        filter(
            None,
            Artwork.objects.values_list("temp_image_path", flat=True),
        )
    )
    for front, back in DesignDraft.objects.values_list(
        "temp_preview_front_path",
        "temp_preview_back_path",
    ):
        if front:
            referenced.add(front)
        if back:
            referenced.add(back)

    now = timezone.now().timestamp()
    deleted = deleted_bytes = 0

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if now - stat.st_mtime < 24 * 60 * 60:
            continue

        relative = path.relative_to(root).as_posix()
        if relative in referenced:
            continue

        try:
            path.unlink()
        except OSError:
            continue
        deleted += 1
        deleted_bytes += stat.st_size

    return {"deleted": deleted, "bytes": deleted_bytes}


@shared_task
def cleanup_orphan_media():
    """Remove old MEDIA_ROOT files that are no longer referenced by DB FileFields."""
    media_root = Path(getattr(settings, "MEDIA_ROOT", ""))
    if not media_root.exists():
        return {"deleted": 0, "bytes": 0, "skipped_recent": 0, "limited": False}

    referenced = set()
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if (
                not getattr(field, "concrete", False)
                or not getattr(field, "attname", None)
                or field.__class__.__name__ not in {"FileField", "ImageField"}
            ):
                continue
            try:
                values = model._default_manager.values_list(
                    field.attname, flat=True
                ).iterator(chunk_size=2000)
                for value in values:
                    name = str(value or "").replace("\\", "/").lstrip("/")
                    if name:
                        referenced.add(name)
                        referenced.update(derivative_names(name))
            except Exception:
                # Never delete files from a model whose references could not be read.
                continue

    now = timezone.now().timestamp()
    grace_seconds = 24 * 60 * 60
    deleted = 0
    deleted_bytes = 0
    skipped_recent = 0

    for root, _, filenames in os.walk(media_root):
        for filename in filenames:
            path = Path(root) / filename
            try:
                stat = path.stat()
            except OSError:
                continue
            if now - stat.st_mtime < grace_seconds:
                skipped_recent += 1
                continue

            name = PurePosixPath(path.relative_to(media_root).as_posix())
            name = str(name)
            if name in referenced:
                continue

            try:
                path.unlink()
            except OSError:
                continue

            deleted += 1
            deleted_bytes += stat.st_size
            if deleted >= 1000:
                return {
                    "deleted": deleted,
                    "bytes": deleted_bytes,
                    "skipped_recent": skipped_recent,
                    "limited": True,
                }

    return {
        "deleted": deleted,
        "bytes": deleted_bytes,
        "skipped_recent": skipped_recent,
        "limited": False,
    }
