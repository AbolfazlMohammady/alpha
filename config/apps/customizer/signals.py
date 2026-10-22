from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.file_cleanup import capture_old_files, delete_model_files, delete_replaced_files
from .ai_models import Product3DAsset, Product3DSource
from .models import Artwork, DesignDraft, DesignerView
from .temp_storage import delete_customizer_temp_file


def _register(sender, fields):
    def pre(sender, instance, **kwargs):
        capture_old_files(sender, instance, fields, **kwargs)

    def post_save_handler(sender, instance, **kwargs):
        delete_replaced_files(sender, instance, fields, **kwargs)

    def post_delete_handler(sender, instance, **kwargs):
        delete_model_files(sender, instance, fields, **kwargs)

    pre_save.connect(pre, sender=sender, dispatch_uid=f"babaei.file.pre.{sender._meta.label_lower}")
    post_save.connect(post_save_handler, sender=sender, dispatch_uid=f"babaei.file.save.{sender._meta.label_lower}")
    post_delete.connect(post_delete_handler, sender=sender, dispatch_uid=f"babaei.file.delete.{sender._meta.label_lower}")


_register(Artwork, ("image", "original_image"))
_register(DesignerView, ("background_image", "mask_image", "model_3d"))
_register(DesignDraft, ("preview_front", "preview_back"))
_register(Product3DAsset, ("model_3d", "preview_image"))
_register(Product3DSource, ("processed_image",))


@receiver(post_delete, sender=Artwork)
def delete_artwork_temporary_file(sender, instance, **kwargs):
    delete_customizer_temp_file(instance.temp_image_path)


@receiver(post_delete, sender=DesignDraft)
def delete_design_temporary_previews(sender, instance, **kwargs):
    delete_customizer_temp_file(instance.temp_preview_front_path)
    delete_customizer_temp_file(instance.temp_preview_back_path)
