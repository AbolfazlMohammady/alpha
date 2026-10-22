from __future__ import annotations

import uuid
from pathlib import Path

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


def product_3d_model_path(instance, filename):
    extension = Path(filename).suffix.lower() or ".glb"
    return f"customizer/generated/{instance.product.uuid}/{uuid.uuid4().hex}{extension}"


def product_3d_preview_path(instance, filename):
    extension = Path(filename).suffix.lower() or ".png"
    return f"customizer/generated/previews/{instance.product.uuid}/{uuid.uuid4().hex}{extension}"


def product_3d_cutout_path(instance, filename):
    extension = Path(filename).suffix.lower() or ".png"
    return f"customizer/generated/cutouts/{instance.asset.product.uuid}/{uuid.uuid4().hex}{extension}"


class Product3DAsset(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", _("در صف آماده‌سازی")
        REMOVING_BACKGROUND = "removing_background", _("در حال حذف پس‌زمینه")
        GENERATING = "generating", _("در حال ساخت مدل سه‌بعدی")
        READY = "ready", _("آماده")
        FAILED = "failed", _("ناموفق")

    class Provider(models.TextChoices):
        MESHY = "meshy", _("Meshy")
        MANUAL = "manual", _("دستی")

    product = models.OneToOneField(
        "shop.Product",
        on_delete=models.CASCADE,
        related_name="three_d_asset",
        verbose_name=_("محصول"),
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.QUEUED, db_index=True)
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.MESHY)
    task_id = models.CharField(max_length=120, blank=True, db_index=True)
    model_3d = models.FileField(upload_to=product_3d_model_path, blank=True, null=True)
    model_url = models.URLField(blank=True)
    preview_image = models.ImageField(upload_to=product_3d_preview_path, blank=True, null=True)
    analysis = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    source_signature = models.CharField(max_length=64, blank=True, db_index=True)
    progress = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return f"3D / {self.product} / {self.status}"


class Product3DSource(models.Model):
    asset = models.ForeignKey(Product3DAsset, on_delete=models.CASCADE, related_name="sources")
    product_image = models.ForeignKey("shop.ProductImage", on_delete=models.CASCADE, related_name="three_d_sources")
    processed_image = models.ImageField(upload_to=product_3d_cutout_path, blank=True, null=True)
    background_removed = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [
            models.UniqueConstraint(fields=("asset", "product_image"), name="unique_3d_source_per_asset_image"),
        ]

    def __str__(self):
        return f"{self.asset.product} / source {self.product_image_id}"
