from __future__ import annotations

from celery import shared_task

from .image_variants import generate_variants_for_product_image


@shared_task(acks_late=True)
def generate_image_variants_for_product_image(image_id):
    return generate_variants_for_product_image(image_id)
