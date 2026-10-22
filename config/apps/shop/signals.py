from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.db import transaction

from apps.file_cleanup import capture_old_files, delete_model_files, delete_replaced_files
from .models import Category, ProductImage
from .tasks import generate_image_variants_for_product_image


@receiver(pre_save, sender=Category)
def category_capture_old_file(sender, instance, **kwargs):
    capture_old_files(sender, instance, ("image",), **kwargs)


@receiver(post_save, sender=Category)
def category_delete_replaced_file(sender, instance, **kwargs):
    delete_replaced_files(sender, instance, ("image",), **kwargs)


@receiver(post_delete, sender=Category)
def category_delete_file(sender, instance, **kwargs):
    delete_model_files(sender, instance, ("image",), **kwargs)


@receiver(pre_save, sender=ProductImage)
def product_image_capture_old_file(sender, instance, **kwargs):
    capture_old_files(sender, instance, ("image",), **kwargs)


@receiver(post_save, sender=ProductImage)
def product_image_delete_replaced_file(sender, instance, **kwargs):
    delete_replaced_files(sender, instance, ("image",), **kwargs)


@receiver(post_delete, sender=ProductImage)
def product_image_delete_file(sender, instance, **kwargs):
    delete_model_files(sender, instance, ("image",), **kwargs)



@receiver(post_save, sender=ProductImage)
def product_image_generate_variants(sender, instance, **kwargs):
    if not instance.image or not instance.image.name:
        return

    created = bool(kwargs.get("created"))
    image_replaced = any(
        with_derivatives
        for _, with_derivatives in getattr(instance, "_babaei_old_files", ())
    )
    if not created and not image_replaced:
        return

    transaction.on_commit(
        lambda image_id=instance.id: generate_image_variants_for_product_image.delay(image_id)
    )
