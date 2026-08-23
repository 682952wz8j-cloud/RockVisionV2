from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .detect import classify_file
from .geospatial import inspect_sidecar
from .hashing import sha256_file
from .images import image_to_json, inspect_image
from .types import (
    MISSING,
    DuplicateGroups,
    ImageInfo,
    InventoryRecord,
    RawAssetType,
    ValidationStatus,
)


def _iso_from_timestamp(value: float | None) -> str:
    if value is None:
        return MISSING
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def filesystem_times(path: Path) -> tuple[str, str]:
    stat = path.stat()
    created = getattr(stat, "st_birthtime", None)
    return _iso_from_timestamp(created), _iso_from_timestamp(stat.st_mtime)


def iter_files(root: Path) -> list[Path]:
    files = [p for p in root.rglob("*") if p.is_file()]
    files.sort(key=lambda p: p.relative_to(root).as_posix())
    return files


def build_record(root: Path, path: Path, relative_path: str | None = None) -> InventoryRecord:
    rel = relative_path if relative_path is not None else path.relative_to(root).as_posix()
    detected_type, method, signature = classify_file(path)
    extra: dict = {}
    status = ValidationStatus.OK
    created, modified = filesystem_times(path)

    if detected_type == RawAssetType.IMAGE:
        image, status = inspect_image(path, signature)
        extra["image"] = image_to_json(image)
    elif detected_type == RawAssetType.RTK_GNSS:
        extra["rtkGnss"] = {
            "parseStatus": "detected but parser not implemented",
            "parsed": False,
        }
        status = ValidationStatus.PARSER_NOT_IMPLEMENTED
    elif detected_type == RawAssetType.ROUTE_GEOMETRY:
        extra["route"] = {"role": "routeGeometryCandidate"}
        status = ValidationStatus.OK
    elif detected_type == RawAssetType.MODEL_3D:
        extra["model3D"] = {"formatHint": path.suffix.lower().lstrip(".") or signature}
        status = ValidationStatus.OK
    elif detected_type == RawAssetType.STRUCTURED_DATA:
        extra["structuredData"] = {"role": "structuredDataCandidate"}
        status = ValidationStatus.OK
    elif detected_type == RawAssetType.METADATA:
        extra["metadata"] = {"role": "metadataCandidate"}
        status = ValidationStatus.OK
    elif detected_type == RawAssetType.GEOSPATIAL_SIDECAR:
        extra["geospatialSidecar"] = inspect_sidecar(path)
        parsed = extra["geospatialSidecar"].get("parsed")
        status = ValidationStatus.OK if parsed else ValidationStatus.DETECTED_UNPARSED
    else:
        status = ValidationStatus.UNKNOWN

    return InventoryRecord(
        relative_path=rel,
        filename=path.name,
        extension=path.suffix.lower(),
        file_size=path.stat().st_size,
        sha256=sha256_file(path),
        detected_type=detected_type,
        detection_method=method,
        validation_status=status,
        mime_or_signature=signature,
        creation_time=created,
        modified_time=modified,
        extra=extra,
    )


def find_duplicates(records: list[InventoryRecord]) -> DuplicateGroups:
    by_hash: dict[str, list[str]] = defaultdict(list)
    by_name: dict[str, list[InventoryRecord]] = defaultdict(list)
    for rec in records:
        by_hash[rec.sha256].append(rec.relative_path)
        by_name[rec.filename].append(rec)

    exact = [paths for paths in by_hash.values() if len(paths) > 1]
    size_by_path = {rec.relative_path: rec.file_size for rec in records}
    nonzero: list[list[str]] = []
    zero_byte: list[list[str]] = []
    for paths in exact:
        if all(size_by_path.get(path, -1) == 0 for path in paths):
            zero_byte.append(paths)
        else:
            nonzero.append(paths)
    same_name_same: list[list[str]] = []
    same_name_diff: list[list[str]] = []
    for group in by_name.values():
        if len(group) < 2:
            continue
        hashes = {item.sha256 for item in group}
        paths = [item.relative_path for item in group]
        if len(hashes) == 1:
            same_name_same.append(paths)
        else:
            same_name_diff.append(paths)
    return DuplicateGroups(exact, nonzero, zero_byte, same_name_same, same_name_diff)


def image_info(record: InventoryRecord) -> ImageInfo | None:
    raw = record.extra.get("image")
    if not raw:
        return None
    return ImageInfo(
        pixel_width=raw.get("pixelWidth", MISSING),
        pixel_height=raw.get("pixelHeight", MISSING),
        has_exif=raw.get("hasExif", MISSING),
        camera_make=raw.get("cameraMake", MISSING),
        camera_model=raw.get("cameraModel", MISSING),
        focal_length=raw.get("focalLength", MISSING),
        focal_length_35mm=raw.get("focalLength35mm", MISSING),
        capture_timestamp=raw.get("captureTimestamp", MISSING),
        gps_latitude=raw.get("gpsLatitude", MISSING),
        gps_longitude=raw.get("gpsLongitude", MISSING),
        gps_altitude=raw.get("gpsAltitude", MISSING),
        orientation=raw.get("orientation", MISSING),
        image_format=raw.get("imageFormat", MISSING),
        lens_model=raw.get("lensModel", MISSING),
    )
