from __future__ import annotations

import shutil
import uuid
from pathlib import Path, PurePosixPath

from django.conf import settings


def get_customizer_temp_root() -> Path:
    configured = getattr(
        settings,
        "CUSTOMIZER_TEMP_ROOT",
        Path(settings.BASE_DIR) / "data" / "customizer_tmp",
    )
    root = Path(configured).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_relative_path(relative_path: str) -> PurePosixPath:
    relative = PurePosixPath(str(relative_path).replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid customizer temporary file path.")
    return relative


def resolve_customizer_temp_path(relative_path: str) -> Path:
    relative = _safe_relative_path(relative_path)
    root = get_customizer_temp_root()
    candidate = (root / Path(*relative.parts)).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Invalid customizer temporary file path.")
    return candidate


def save_uploaded_file_to_temp(file_obj, *, directory: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".bin"
    relative = PurePosixPath(directory) / f"{uuid.uuid4().hex}{suffix}"
    target = resolve_customizer_temp_path(str(relative))
    target.parent.mkdir(parents=True, exist_ok=True)

    file_obj.seek(0)
    with target.open("wb") as destination:
        for chunk in file_obj.chunks():
            destination.write(chunk)

    return relative.as_posix()


def save_bytes_to_temp(data: bytes, *, directory: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".bin"
    relative = PurePosixPath(directory) / f"{uuid.uuid4().hex}{suffix}"
    target = resolve_customizer_temp_path(str(relative))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative.as_posix()


def delete_customizer_temp_file(relative_path: str | None) -> None:
    if not relative_path:
        return
    try:
        path = resolve_customizer_temp_path(relative_path)
    except (TypeError, ValueError):
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return
