from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.file_cleanup import capture_old_files, delete_model_files, delete_replaced_files
from .models import User


@receiver(pre_save, sender=User)
def user_capture_old_file(sender, instance, **kwargs):
    capture_old_files(sender, instance, ("image",), **kwargs)


@receiver(post_save, sender=User)
def user_delete_replaced_file(sender, instance, **kwargs):
    delete_replaced_files(sender, instance, ("image",), **kwargs)


@receiver(post_delete, sender=User)
def user_delete_file(sender, instance, **kwargs):
    delete_model_files(sender, instance, ("image",), **kwargs)
