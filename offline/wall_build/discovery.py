"""Recursive incoming inventory. Candidates only; no capture selection."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

from offline.ingestion.scan import build_record, find_duplicates, iter_files
from offline.ingestion.types import RawAssetType
from offline.ingestion.validate import is_readable_image

from .states import ReasonCode


def _candidate_id(kind: str, wall_id: str, key: str) -> str:
    digest = hashlib.sha256(f"{wall_id}:{kind}:{key}".encode("utf-8")).hexdigest()[:12]
    return f"{kind}_{digest}"


def scan_wall_records(incoming: Path) -> list:
    if not incoming.is_dir():
        return []
    records = []
    for path in iter_files(incoming):
        records.append(build_record(incoming, path))
    return records


def _is_mrk(record) -> bool:
    name = record.filename.lower()
    method = record.detection_method
    return record.detected_type == RawAssetType.RTK_GNSS and (
        record.extension == ".mrk" or name.endswith(".mrk") or "dji_mrk" in method
    )


def _is_metadata_xml(record) -> bool:
    return record.filename.lower() == "metadata.xml"


def _is_dxf(record) -> bool:
    return record.extension == ".dxf" or record.filename.lower().endswith(".dxf")


def _is_gnss_aux(record) -> bool:
    return record.detected_type == RawAssetType.RTK_GNSS and not _is_mrk(record)


def _capture_key(relative_path: str) -> str:
    parts = relative_path.replace("\\", "/").split("/")
    if len(parts) == 1:
        return "."
    return parts[0]


def _looks_like_dji_dir(name: str) -> bool:
    return name.upper().startswith("DJI_") or name.upper().startswith("DJI")


def build_discovery(wall_id: str, incoming: Path, records: list) -> dict:
    images = [r for r in records if r.detected_type == RawAssetType.IMAGE]
    readable = [r for r in images if is_readable_image(r)]
    mrk = [r for r in records if _is_mrk(r)]
    metadata = [r for r in records if _is_metadata_xml(r)]
    gnss_aux = [r for r in records if _is_gnss_aux(r)]
    dxf = [r for r in records if _is_dxf(r)]
    models = [r for r in records if r.detected_type == RawAssetType.MODEL_3D]
    measurement = [
        r
        for r in records
        if r.detected_type.value in {"geospatialSidecar", "structuredData", "metadata"}
        and not _is_metadata_xml(r)
    ]
    unknown = [r for r in records if r.detected_type == RawAssetType.UNKNOWN]
    duplicates = find_duplicates(records)

    by_capture: dict[str, list] = defaultdict(list)
    for record in images:
        by_capture[_capture_key(record.relative_path)].append(record)

    capture_candidates = []
    for key, group in sorted(by_capture.items()):
        evidence = [r.relative_path for r in group]
        dji = _looks_like_dji_dir(key) if key != "." else False
        capture_candidates.append(
            {
                "captureCandidateId": _candidate_id("cap", wall_id, key),
                "relativeDirectory": key,
                "djiFolderHint": dji,
                "imageCount": len(group),
                "readableImageCount": sum(1 for r in group if is_readable_image(r)),
                "evidence": evidence,
                "selected": False,
                "selectionStatus": "NOT_SELECTED",
            }
        )

    ignored = [
        {
            "relativePath": r.relative_path,
            "classification": ReasonCode.IGNORED_UNKNOWN_FILE.value,
            "fileSize": r.file_size,
            "checksum": r.sha256,
        }
        for r in unknown
    ]

    warnings: list[str] = []
    if len(capture_candidates) > 1:
        warnings.append(ReasonCode.MULTIPLE_CAPTURE_CANDIDATES.value)
    if len(mrk) > 1:
        warnings.append(ReasonCode.MULTIPLE_MRK_CANDIDATES.value)
    if len(metadata) > 1:
        warnings.append(ReasonCode.MULTIPLE_METADATA_CANDIDATES.value)
    if len(models) > 1:
        warnings.append(ReasonCode.MULTIPLE_MODEL_CANDIDATES.value)
    if ignored:
        warnings.append(ReasonCode.IGNORED_UNKNOWN_FILE.value)

    return {
        "wallId": wall_id,
        "discoveredFileCount": len(records),
        "classifiedInputs": {
            "images": [_file_ref(r) for r in images],
            "mrk": [_file_ref(r) for r in mrk],
            "metadataXml": [_file_ref(r) for r in metadata],
            "gnssAuxiliary": [_file_ref(r) for r in gnss_aux],
            "dxf": [_file_ref(r) for r in dxf],
            "models": [_file_ref(r) for r in models],
            "measurementRelated": [_file_ref(r) for r in measurement],
        },
        "ignoredUnknownFiles": ignored,
        "captureCandidates": capture_candidates,
        "mrkCandidates": [_file_ref(r) for r in mrk],
        "metadataCandidates": [_file_ref(r) for r in metadata],
        "modelCandidates": [_file_ref(r) for r in models],
        "dxfFiles": [_file_ref(r) for r in dxf],
        "imageCount": len(images),
        "readableImageCount": len(readable),
        "duplicateGroups": {
            "exact": duplicates.exact_duplicates,
            "contentNonZero": duplicates.content_duplicates_nonzero,
            "zeroByteIdentical": duplicates.zero_byte_identical,
            "sameNameDifferentContent": duplicates.same_name_different_content,
        },
        "inventoryWarnings": warnings,
        "authoritativeCaptureSelected": False,
        "status": "AUTO_PASS" if incoming.is_dir() else "AUTO_FAIL",
    }


def _file_ref(record) -> dict:
    classification = record.detected_type.value if hasattr(record.detected_type, "value") else str(record.detected_type)
    return {
        "relativePath": record.relative_path,
        "sourceFilename": record.filename,
        "extension": record.extension,
        "fileSize": record.file_size,
        "checksum": record.sha256,
        "classification": classification,
        "detectionMethod": record.detection_method,
        "mimeOrSignature": record.mime_or_signature,
        "zeroByte": record.file_size == 0,
    }
