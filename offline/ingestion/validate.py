"""Gate 1A validation result rules.

These rules are fixed. Do not change them ad hoc for a particular wall.

FAIL when any of:
  - incoming/wall_<id>/ does not exist
  - incoming/wall_<id>/ is not a readable directory
  - the tree cannot be listed
  - no image could be opened for pixel width/height (images_readable == 0)
  - any incoming file hash or path changed during the run

PASS when:
  - images_readable >= 1
  - the warnings list is empty

PASS WITH WARNINGS when:
  - images_readable >= 1
  - at least one non-blocking warning exists

Non-blocking warnings:
  - an image is missing EXIF or GPS
  - RTK/GNSS candidates were detected but no parser is implemented
  - unknown files are present
  - non-zero content duplicate groups are present
  - same filename / different content is present
  - zero-byte identical files are reported separately and are not
    treated as duplicated photographs or models
  - some image candidates could not be decoded, while at least one other
    image is readable
  - incoming immutability could not be proven (treated as FAIL instead)

Missing optional types (no model, no route, no RTK) are not warnings.
"""

from __future__ import annotations

from .types import (
    MISSING,
    DuplicateGroups,
    ImageInfo,
    InventoryRecord,
    RawAssetType,
    RunResult,
    ValidationStatus,
)


def _image(record: InventoryRecord) -> ImageInfo | None:
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


def is_readable_image(record: InventoryRecord) -> bool:
    info = _image(record)
    return bool(
        record.detected_type == RawAssetType.IMAGE
        and info is not None
        and isinstance(info.pixel_width, int)
        and isinstance(info.pixel_height, int)
    )


def has_gps(info: ImageInfo) -> bool:
    return info.gps_latitude != MISSING and info.gps_longitude != MISSING


def collect_warnings(
    records: list[InventoryRecord],
    duplicates: DuplicateGroups,
) -> list[str]:
    warnings: list[str] = []
    images = [r for r in records if r.detected_type == RawAssetType.IMAGE]
    readable = [r for r in images if is_readable_image(r)]
    unreadable = [r for r in images if not is_readable_image(r)]

    missing_exif = 0
    missing_gps = 0
    for record in readable:
        info = _image(record)
        if info is None:
            continue
        if info.has_exif is not True:
            missing_exif += 1
        if not has_gps(info):
            missing_gps += 1
    if missing_exif:
        warnings.append(f"{missing_exif} readable image(s) missing EXIF")
    if missing_gps:
        warnings.append(f"{missing_gps} readable image(s) missing GPS")

    rtk = [r for r in records if r.detected_type == RawAssetType.RTK_GNSS]
    unparsed = [
        r
        for r in rtk
        if r.validation_status
        in {ValidationStatus.PARSER_NOT_IMPLEMENTED, ValidationStatus.DETECTED_UNPARSED}
    ]
    if unparsed:
        warnings.append(
            f"{len(unparsed)} RTK/GNSS candidate(s) detected but parser not implemented"
        )

    unknown = [r for r in records if r.detected_type == RawAssetType.UNKNOWN]
    if unknown:
        warnings.append(f"{len(unknown)} unknown file(s) retained in inventory")

    if duplicates.content_duplicates_nonzero:
        warnings.append(
            f"{len(duplicates.content_duplicates_nonzero)} non-zero content duplicate group(s) found; nothing deleted"
        )
    if duplicates.same_name_different_content:
        warnings.append(
            f"{len(duplicates.same_name_different_content)} same-filename / different-content group(s)"
        )
    if unreadable and readable:
        warnings.append(
            f"{len(unreadable)} image candidate(s) could not be decoded"
        )
    return warnings


def decide_result(
    *,
    wall_exists: bool,
    wall_accessible: bool,
    images_readable: int,
    incoming_unchanged: bool,
    warnings: list[str],
    listing_error: str | None = None,
) -> tuple[RunResult, list[str]]:
    errors: list[str] = []
    if not wall_exists:
        errors.append("incoming wall directory does not exist")
    elif not wall_accessible:
        errors.append("incoming wall directory is not accessible")
    if listing_error:
        errors.append(listing_error)
    if wall_exists and wall_accessible and listing_error is None and images_readable == 0:
        errors.append("no readable photographs found")
    if not incoming_unchanged:
        errors.append("incoming files changed during ingestion; incoming must remain immutable")
    if errors:
        return RunResult.FAIL, errors
    if warnings:
        return RunResult.PASS_WITH_WARNINGS, errors
    return RunResult.PASS, errors
