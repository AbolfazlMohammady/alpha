from __future__ import annotations

from pathlib import PurePosixPath

from django.db import transaction


def _delete(storage, name):
    if not name:
        return
    try:
        if storage.exists(name):
            storage.delete(name)
    except (OSError, ValueError):
        # Storage cleanup must never break a successful database transaction.
        pass


def delete_file_later(field_file):
    if not field_file or not getattr(field_file, "name", None):
        return
    storage = field_file.storage
    name = field_file.name
    transaction.on_commit(lambda: _delete(storage, name))


def delete_name_later(storage, name):
    if name:
        transaction.on_commit(lambda: _delete(storage, name))


def derivative_names(source_name):
    """Return all responsive image derivatives generated for a source."""
    if not source_name:
        return ()
    path = PurePosixPath(source_name)
    return tuple(
        f"{path.with_suffix('')}-{width}.{extension}"
        for width in (400, 640, 900)
        for extension in ("webp", "avif")
    )


def delete_with_derivatives_later(field_file):
    if not field_file or not getattr(field_file, "name", None):
        return
    storage = field_file.storage
    names = (field_file.name, *derivative_names(field_file.name))

    def cleanup():
        for name in names:
            _delete(storage, name)

    transaction.on_commit(cleanup)


def capture_old_files(sender, instance, fields, **kwargs):
    if kwargs.get("raw") or not instance.pk:
        return

    try:
        old = sender._default_manager.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    changed = []
    for field_name in fields:
        old_file = getattr(old, field_name, None)
        new_file = getattr(instance, field_name, None)
        old_name = getattr(old_file, "name", "") or ""
        new_name = getattr(new_file, "name", "") or ""
        if old_name and old_name != new_name:
            changed.append((old_file, field_name == "image"))

    if changed:
        instance._babaei_old_files = changed


def delete_replaced_files(sender, instance, fields, **kwargs):
    changed = getattr(instance, "_babaei_old_files", ())
    for old_file, with_derivatives in changed:
        if with_derivatives:
            delete_with_derivatives_later(old_file)
        else:
            delete_file_later(old_file)


def delete_model_files(sender, instance, fields, **kwargs):
    for field_name in fields:
        field_file = getattr(instance, field_name, None)
        if field_name == "image":
            delete_with_derivatives_later(field_file)
        else:
            delete_file_later(field_file)
