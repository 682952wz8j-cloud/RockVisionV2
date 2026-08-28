"""COMPATIBLE_PRIMARY_CAPTURE predicate and evidence-preserving grouping.

one directory = one capture is not a universal rule.
Grouping keys (parent, DJI filename date) are evidence, not a fail condition.
"""

from __future__ import annotations

from pathlib import Path

from offline.qualification.associate import dji_filename_parts
from offline.qualification.images import DJI_NAME, IPHONE_NAME

from .states import ReasonCode


def compatible_primary_capture(image: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    name = image.get("filename") or ""
    role = image.get("role")
    ext = Path(name).suffix.lower()
    make = str(image.get("cameraMake") or "")
    width = (image.get("dimensions") or {}).get("width")
    height = (image.get("dimensions") or {}).get("height")

    if role != "originalCameraImage":
        reasons.append(f"role={role} is not originalCameraImage")
    if ext in {".heic", ".heif"}:
        reasons.append("HEIC/HEIF is not a Generic Stage 2 primary capture")
    if IPHONE_NAME.match(name) or "iphone" in str(image.get("cameraModel") or "").lower():
        reasons.append("iPhone capture is excluded")
    if role in {"textureAsset", "derivedModelingImage", "orthophotoOrRaster"}:
        reasons.append(f"role {role} is texture/tile/report/raster, not a camera exposure")
    if not DJI_NAME.match(name):
        reasons.append("filename is not a standard DJI camera structure")
    if make.lower() in {"", "missing"}:
        reasons.append("EXIF camera make is missing")
    if not image.get("colmapSourceCandidate"):
        reasons.append("not classified as a COLMAP-eligible original camera image")
    if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
        reasons.append("image is not readable / lacks valid pixel dimensions")
    return (not reasons), reasons


def group_compatible_captures(images: list[dict]) -> tuple[list[dict], list[dict]]:
    groups: dict[tuple[str, str], dict] = {}
    rejected: list[dict] = []
    for image in images:
        ok, reasons = compatible_primary_capture(image)
        rel = image.get("relativePath") or ""
        parts = dji_filename_parts(image.get("filename") or "")
        parent = Path(rel).parent.as_posix() if rel else "."
        date = parts["date"] if parts else "unknown"
        record = {
            "relativePath": rel,
            "filename": image.get("filename"),
            "parentDirectory": parent,
            "filenameDate": date,
            "filenameSequence": parts["sequence"] if parts else None,
            "exifTimestamp": image.get("captureTimestamp"),
            "cameraMake": image.get("cameraMake"),
            "cameraModel": image.get("cameraModel"),
            "sha256": image.get("sha256"),
            "role": image.get("role"),
            "compatible": ok,
            "rejectionReasons": reasons,
        }
        if not ok:
            rejected.append(record)
            continue
        key = (parent, date)
        bucket = groups.setdefault(
            key,
            {
                "groupId": f"{parent}|{date}",
                "parentDirectory": parent,
                "filenameDate": date,
                "groupingKeys": {
                    "parentDirectory": parent,
                    "djiFilenameDate": date,
                    "notUniversalOneDirectoryRule": True,
                },
                "members": [],
                "memberRelativePaths": [],
                "filenameEvidence": [],
                "exifEvidence": [],
                "sourcePaths": [],
            },
        )
        bucket["members"].append(record)
        bucket["memberRelativePaths"].append(rel)
        bucket["filenameEvidence"].append(
            {
                "filename": record["filename"],
                "sequence": record["filenameSequence"],
                "date": date,
            }
        )
        bucket["exifEvidence"].append(
            {
                "relativePath": rel,
                "captureTimestamp": record["exifTimestamp"],
                "cameraMake": record["cameraMake"],
            }
        )
        bucket["sourcePaths"].append(rel)

    ordered = [groups[key] for key in sorted(groups)]
    for group in ordered:
        group["memberCount"] = len(group["members"])
        group["memberRelativePaths"].sort()
    return ordered, rejected


def selectable_capture_conflict(selectable: list[dict]) -> dict | None:
    if len(selectable) <= 1:
        return None
    return {
        "status": "HUMAN_REVIEW_REQUIRED",
        "reasonCode": ReasonCode.MULTIPLE_SELECTABLE_CAPTURE_GROUPS.value,
        "detail": "Approved rules leave two or more complete legal capture groups.",
        "groupIds": [g.get("groupId") for g in selectable],
    }
