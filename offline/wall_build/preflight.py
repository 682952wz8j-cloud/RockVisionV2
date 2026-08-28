"""Deterministic preflight. Not stricter than Gate 1A on required images."""

from __future__ import annotations

from pathlib import Path

from offline.ingestion.types import RawAssetType
from offline.ingestion.validate import is_readable_image

from .states import ReasonCode, StageStatus
from .wall_id import wall_id_error


RECOGNIZED_TYPES = {
    RawAssetType.IMAGE,
    RawAssetType.RTK_GNSS,
    RawAssetType.MODEL_3D,
    RawAssetType.ROUTE_GEOMETRY,
    RawAssetType.STRUCTURED_DATA,
    RawAssetType.METADATA,
    RawAssetType.GEOSPATIAL_SIDECAR,
}


def run_preflight(
    *,
    wall_id: str,
    incoming: Path,
    records: list,
    discovery: dict,
) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    reason_codes: list[str] = []

    id_error = wall_id_error(wall_id)
    if id_error is not None:
        return _fail([id_error.value], errors=["invalid wall_id"], warnings=[])

    if not incoming.exists():
        return _fail(
            [ReasonCode.MISSING_WALL_DIRECTORY.value],
            errors=["incoming wall directory does not exist"],
            warnings=[],
        )
    if not incoming.is_dir():
        return _fail(
            [ReasonCode.WALL_PATH_NOT_DIRECTORY.value],
            errors=["incoming wall path is not a directory"],
            warnings=[],
        )

    try:
        incoming.resolve().relative_to(incoming.parent.resolve())
    except ValueError:
        return _fail(
            [ReasonCode.UNSAFE_WALL_PATH.value],
            errors=["incoming wall path is not a valid wall directory"],
            warnings=[],
        )

    recognized = [r for r in records if r.detected_type in RECOGNIZED_TYPES]
    images = [r for r in records if r.detected_type == RawAssetType.IMAGE]
    readable = [r for r in images if is_readable_image(r)]
    zero_byte = [r for r in recognized if r.file_size == 0]
    zero_byte_route = [r for r in zero_byte if r.detected_type == RawAssetType.ROUTE_GEOMETRY]
    zero_byte_other = [r for r in zero_byte if r.detected_type != RawAssetType.ROUTE_GEOMETRY]
    if zero_byte_other:
        warnings.append(ReasonCode.ZERO_BYTE_RECOGNIZED_INPUT.value)
        reason_codes.append(ReasonCode.ZERO_BYTE_RECOGNIZED_INPUT.value)

    duplicates = discovery.get("duplicateGroups") or {}
    if duplicates.get("contentNonZero") or duplicates.get("exact"):
        warnings.append("DUPLICATE_FILES_WARNING")

    if discovery.get("inventoryWarnings"):
        warnings.extend(discovery["inventoryWarnings"])

    # Gate 1A: images_readable >= 1. Do not raise a higher Stage 2 image-count bar.
    if len(readable) < 1:
        errors.append("no readable photographs found")
        reason_codes.append(ReasonCode.MISSING_REQUIRED_SOURCE_IMAGES.value)
        return _fail(reason_codes, errors=errors, warnings=warnings)

    dxf_parse_failures = [
        item
        for item in discovery.get("dxfParseResults") or []
        if item.get("parseStatus") == StageStatus.AUTO_FAIL.value
    ]
    corrupt_names: list[str] = []
    seen: set[str] = set()
    for item in dxf_parse_failures:
        name = item.get("sourceFilename") or item.get("relativePath") or "unknown.dxf"
        if name not in seen:
            seen.add(name)
            corrupt_names.append(name)
    for record in zero_byte_route:
        name = record.filename
        if name not in seen:
            seen.add(name)
            corrupt_names.append(name)

    checks = {
        "wallDirectoryExists": True,
        "wallPathIsDirectory": True,
        "recognizedFileCount": len(recognized),
        "imageCount": len(images),
        "imagesReadable": len(readable),
        "imagesWithExif": sum(
            1
            for r in readable
            if (r.extra.get("image") or {}).get("hasExif") is True
        ),
        "zeroByteRecognizedInputs": [r.relative_path for r in zero_byte],
        "zeroByteRouteGeometry": [r.relative_path for r in zero_byte_route],
        "mrkCandidateCount": len(discovery.get("mrkCandidates") or []),
        "metadataCandidateCount": len(discovery.get("metadataCandidates") or []),
        "dxfCandidateCount": len(discovery.get("dxfFiles") or []),
        "modelCandidateCount": len(discovery.get("modelCandidates") or []),
        "captureCandidateCount": len(discovery.get("captureCandidates") or []),
        "duplicateContentGroups": len(duplicates.get("contentNonZero") or []),
        "dxfParseFailures": len(dxf_parse_failures),
        "corruptRouteGeometryFiles": corrupt_names,
    }

    if corrupt_names:
        return _fail(
            [ReasonCode.CORRUPT_DXF.value],
            errors=[f"corrupt DXF: {name}" for name in corrupt_names],
            warnings=warnings,
            checks=checks,
        )

    return {
        "status": StageStatus.AUTO_PASS.value,
        "reasonCodes": reason_codes,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def _fail(
    reason_codes: list[str],
    *,
    errors: list[str],
    warnings: list[str],
    checks: dict | None = None,
) -> dict:
    return {
        "status": StageStatus.AUTO_FAIL.value,
        "reasonCodes": reason_codes,
        "errors": errors,
        "warnings": warnings,
        "checks": checks or {},
    }
