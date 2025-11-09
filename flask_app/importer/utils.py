"""
Importer-specific utilities for handling uploaded files and cleanup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable
from uuid import uuid4

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


DEFAULT_UPLOAD_SUBDIR = "import_uploads"
CSV_EXTENSIONS: tuple[str, ...] = ("csv",)


def _normalize_upload_dir(configured_path: str | None, instance_path: str) -> Path:
    if not configured_path:
        return Path(instance_path) / DEFAULT_UPLOAD_SUBDIR

    candidate = Path(configured_path)
    if candidate.is_absolute():
        return candidate

    return Path(instance_path) / candidate


def resolve_upload_directory(app) -> Path:
    """
    Determine and create (if necessary) the importer upload directory.
    """

    upload_dir = _normalize_upload_dir(app.config.get("IMPORTER_UPLOAD_DIR"), app.instance_path)
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def allowed_file(filename: str, allowed_extensions: Iterable[str] = CSV_EXTENSIONS) -> bool:
    """
    Validate the uploaded filename extension against the allowed set.
    """

    if not filename or "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in {ext.lower() for ext in allowed_extensions}


def persist_upload(file_storage: FileStorage, app, *, suffix: str | None = None) -> Path:
    """
    Persist the uploaded file to disk and return the fully-qualified path.

    Files are stored under ``resolve_upload_directory(app)`` using a UUID-based
    filename to avoid collisions. The original extension is preserved when
    possible.
    """

    upload_dir = resolve_upload_directory(app)
    original_name = secure_filename(file_storage.filename or "")
    extension = Path(original_name).suffix if original_name else ""
    if not extension and suffix:
        extension = suffix if suffix.startswith(".") else f".{suffix}"
    if not extension:
        extension = ".csv"

    target_path = upload_dir / f"{uuid4().hex}{extension}"
    file_storage.save(target_path)
    current_app.logger.debug("Importer upload persisted to %s", target_path)
    return target_path


def cleanup_upload(path: Path) -> None:
    """
    Remove a stored upload, logging but ignoring filesystem errors.
    """

    try:
        path.unlink(missing_ok=True)
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.warning("Failed to remove importer upload %s: %s", path, exc)

