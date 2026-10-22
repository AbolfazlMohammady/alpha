from __future__ import annotations

from pathlib import Path
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.file_cleanup import derivative_names


def human(size):
    size = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.1f} {unit}"
        size /= 1024


class Command(BaseCommand):
    help = "Find and optionally remove media files that are not referenced by the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Actually delete unreferenced files. Without this flag the command is read-only.",
        )
        parser.add_argument(
            "--min-age-hours",
            type=int,
            default=24,
            help="Only consider files older than this many hours (default: 24).",
        )
        parser.add_argument(
            "--empty-dirs",
            action="store_true",
            help="Remove empty directories after deleting orphan files.",
        )

    def handle(self, *args, **options):
        media_root = Path(settings.MEDIA_ROOT).resolve()
        if not media_root.exists():
            self.stdout.write(self.style.WARNING(f"MEDIA_ROOT does not exist: {media_root}"))
            return

        referenced = set()
        derivative_sources = []

        for model in apps.get_models():
            for field in model._meta.fields:
                if not getattr(field, "upload_to", None):
                    continue
                if field.get_internal_type() not in {"FileField", "ImageField"}:
                    continue
                for value in model._default_manager.values_list(field.name, flat=True).iterator():
                    if value:
                        name = str(value).lstrip("/")
                        referenced.add(name)

        # Responsive derivatives are intentionally not stored in the DB.
        # Protect derivatives belonging to currently referenced ProductImage files.
        from apps.shop.models import ProductImage

        for name in ProductImage.objects.exclude(image="").values_list("image", flat=True).iterator():
            derivative_sources.extend(derivative_names(str(name)))

        referenced.update(derivative_sources)

        cutoff = __import__("datetime").datetime.now().timestamp() - options["min_age_hours"] * 3600
        orphan_files = []
        orphan_bytes = 0

        for path in media_root.rglob("*"):
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(media_root).as_posix()
                mtime = path.stat().st_mtime
                size = path.stat().st_size
            except OSError:
                continue

            if relative in referenced or mtime > cutoff:
                continue

            orphan_files.append((path, relative, size))
            orphan_bytes += size

        self.stdout.write(f"MEDIA_ROOT: {media_root}")
        self.stdout.write(f"Referenced files: {len(referenced):,}")
        self.stdout.write(f"Orphan candidates: {len(orphan_files):,} ({human(orphan_bytes)})")

        if not orphan_files:
            self.stdout.write(self.style.SUCCESS("No orphan media files found."))
            return

        for path, relative, size in orphan_files:
            if options["delete"]:
                try:
                    path.unlink()
                except OSError as exc:
                    self.stdout.write(self.style.ERROR(f"failed: {relative}: {exc}"))
                    continue
                self.stdout.write(f"deleted: {relative} ({human(size)})")
            else:
                self.stdout.write(f"candidate: {relative} ({human(size)})")

        if options["delete"] and options["empty_dirs"]:
            for directory in sorted(
                (p for p in media_root.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts),
                reverse=True,
            ):
                try:
                    directory.rmdir()
                except OSError:
                    pass

        if not options["delete"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run only. Review the candidates, then rerun with --delete to remove them."
                )
            )
