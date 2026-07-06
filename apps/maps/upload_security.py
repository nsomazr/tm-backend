"""Shared upload validation for map layers and admin boundary imports."""

from __future__ import annotations

import shutil
import struct
import zipfile
from pathlib import Path
from typing import Any

from django.conf import settings

ALLOWED_UPLOAD_EXTENSIONS = frozenset(
    {
        ".zip",
        ".shp",
        ".geojson",
        ".json",
    }
)


class UploadValidationError(ValueError):
    """Raised when an upload fails security or size checks."""


def _setting(name: str, default: int) -> int:
    return int(getattr(settings, name, default))


def max_upload_bytes(*, boundary: bool = False) -> int:
    if boundary:
        return _setting("BOUNDARY_UPLOAD_MAX_BYTES", _setting("MAP_UPLOAD_MAX_BYTES", 50 * 1024 * 1024))
    return _setting("MAP_UPLOAD_MAX_BYTES", 50 * 1024 * 1024)


def max_feature_count(*, boundary: bool = False) -> int:
    if boundary:
        return _setting("BOUNDARY_UPLOAD_MAX_FEATURES", 100_000)
    return _setting("MAP_UPLOAD_MAX_FEATURES", 50_000)


def _format_mb(num_bytes: int) -> int:
    return max(1, num_bytes // (1024 * 1024))


def validate_upload_filename(filename: str) -> None:
    name = (filename or "").strip()
    if not name:
        raise UploadValidationError("Upload filename is required.")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise UploadValidationError(
            "Unsupported file type. Upload a .zip shapefile bundle, .geojson, or .json file."
        )


def validate_upload_size(size: int, *, boundary: bool = False) -> None:
    limit = max_upload_bytes(boundary=boundary)
    if size <= 0:
        raise UploadValidationError("Upload file is empty.")
    if size > limit:
        raise UploadValidationError(
            f"File too large. Maximum size is {_format_mb(limit)} MB."
        )


def validate_upload_bytes(content: bytes, filename: str, *, boundary: bool = False) -> None:
    validate_upload_filename(filename)
    validate_upload_size(len(content), boundary=boundary)


def validate_feature_count(count: int, *, boundary: bool = False) -> None:
    limit = max_feature_count(boundary=boundary)
    if count > limit:
        raise UploadValidationError(
            f"Upload contains too many features ({count:,}). "
            f"The limit is {limit:,}. Split the file or simplify geometries."
        )


def validate_parsed_features(features: list[dict[str, Any]], *, boundary: bool = False) -> None:
    validate_feature_count(len(features), boundary=boundary)


def check_disk_headroom(*, boundary: bool = False) -> None:
    min_free = _setting(
        "BOUNDARY_IMPORT_MIN_FREE_BYTES" if boundary else "MAP_UPLOAD_MIN_FREE_BYTES",
        512 * 1024 * 1024,
    )
    path = getattr(settings, "MEDIA_ROOT", settings.BASE_DIR)
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return
    if usage.free < min_free:
        raise UploadValidationError(
            "The server is low on disk space, so the upload cannot be processed. "
            f"Free at least {_format_mb(min_free)} MB on the backend machine, then try again. "
            "GeoJSON is often smaller than a shapefile ZIP."
        )


def _is_mac_junk(name: str) -> bool:
    lower = name.lower()
    if lower.startswith("__macosx/"):
        return True
    basename = name.rsplit("/", 1)[-1]
    return basename.startswith("._")


def _zip_entry_is_safe(name: str) -> bool:
    normalized = name.replace("\\", "/").strip()
    if not normalized or normalized.startswith("/"):
        return False
    parts = [part for part in normalized.split("/") if part]
    if any(part == ".." for part in parts):
        return False
    return True


def validate_zip_archive(zf: zipfile.ZipFile, compressed_size: int) -> None:
    max_entries = _setting("MAP_ZIP_MAX_ENTRIES", 200)
    max_uncompressed = _setting("MAP_ZIP_MAX_UNCOMPRESSED_BYTES", 100 * 1024 * 1024)
    max_ratio = _setting("MAP_ZIP_MAX_COMPRESSION_RATIO", 100)

    entries = [info for info in zf.infolist() if not _is_mac_junk(info.filename)]
    if len(entries) > max_entries:
        raise UploadValidationError("ZIP contains too many files.")

    total_uncompressed = 0
    for info in entries:
        if not _zip_entry_is_safe(info.filename):
            raise UploadValidationError("ZIP contains unsafe file paths.")
        total_uncompressed += info.file_size

    if total_uncompressed > max_uncompressed:
        raise UploadValidationError("ZIP uncompressed size exceeds limit.")

    if compressed_size > 0 and total_uncompressed / compressed_size > max_ratio:
        raise UploadValidationError("ZIP compression ratio looks unsafe. Re-export the archive.")


def friendly_upload_error(exc: Exception) -> str:
    if isinstance(exc, UploadValidationError):
        return str(exc)

    message = str(exc).lower()
    errno = getattr(exc, "errno", None)

    if isinstance(exc, UnicodeDecodeError):
        return (
            "Could not read attribute data (.dbf). "
            "Re-export the shapefile with UTF-8 or Latin-1 text fields, "
            "or upload GeoJSON instead."
        )
    if errno == 28 or "no space left on device" in message:
        return (
            "The server is out of disk space, so the upload could not be saved. "
            "Free at least 1-2 GB on the machine running the backend, then upload again. "
            "A GeoJSON file is often smaller than a shapefile ZIP."
        )
    if "duplicate" in message and ("entry" in message or "key" in message):
        return (
            "Some records use duplicate codes. "
            "Re-export with unique names or GADM-style GID codes."
        )
    if "connection" in message and "refused" in message:
        return "Could not reach the database. Check that MySQL is running and try again."
    if "max_allowed_packet" in message:
        return (
            "Import failed: feature batch is too large for the database. "
            "Try simplifying geometries, splitting the layer, or increasing MySQL max_allowed_packet."
        )
    if isinstance(exc, struct.error):
        return (
            "Could not read the shapefile inside the ZIP. "
            "Zip the .shp, .shx, and .dbf together (same folder), "
            "or export GeoJSON instead."
        )
    if "memory" in message or isinstance(exc, MemoryError):
        return (
            "The upload is too large to process in memory. "
            "Try GeoJSON, fewer features, or simplified geometries."
        )
    if "zip" in message or "geojson" in message or "shapefile" in message:
        return str(exc)
    return "Import failed. Check the file format and try again, or upload GeoJSON instead."
