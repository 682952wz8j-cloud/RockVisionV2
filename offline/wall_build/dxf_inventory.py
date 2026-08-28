"""Complete DXF inventory. Parse facts only. No WallMetricMeters provenance."""

from __future__ import annotations

import hashlib
from pathlib import Path

from offline.qualification.dxf_geom import parse_dxf_file

from .states import ReasonCode, StageStatus


def _internal_id(wall_id: str, checksum: str, relative_path: str) -> str:
    digest = hashlib.sha256(f"{wall_id}:{checksum}:{relative_path}".encode("utf-8")).hexdigest()[:12]
    return f"rc_{digest}"


def inventory_dxf_files(wall_id: str, incoming: Path, dxf_refs: list[dict]) -> list[dict]:
    results = []
    for ref in dxf_refs:
        rel = ref["relativePath"]
        path = incoming / rel
        item = {
            "sourceFilename": ref.get("sourceFilename") or path.name,
            "relativePath": rel,
            "sourceChecksum": ref.get("checksum"),
            "wallId": wall_id,
            "routeCandidateId": _internal_id(wall_id, ref.get("checksum") or "", rel),
            "fileSize": ref.get("fileSize"),
            "discoveryStatus": StageStatus.AUTO_PASS.value,
            "parseStatus": StageStatus.AUTO_FAIL.value,
            "reasonCode": None,
            "geometry": None,
            "coordinateFrame": None,
            "wallMetricMetersProvenance": "NOT_CLAIMED",
            "authoringFrameId": None,
            "authoringProvenanceGroup": None,
        }
        if not path.is_file():
            item["reasonCode"] = ReasonCode.CORRUPT_DXF.value
            item["parseDetail"] = "DXF path is not a readable file"
            results.append(item)
            continue
        try:
            geom = parse_dxf_file(path)
        except (OSError, UnicodeError, ValueError) as exc:
            item["reasonCode"] = ReasonCode.CORRUPT_DXF.value
            item["parseDetail"] = f"{type(exc).__name__}: {exc}"
            results.append(item)
            continue
        looks_like = "content:dxf" in (ref.get("detectionMethod") or "")
        if not looks_like:
            item["reasonCode"] = ReasonCode.CORRUPT_DXF.value
            item["parseDetail"] = "file does not contain recognizable DXF SECTION structure"
            results.append(item)
            continue
        item["parseStatus"] = StageStatus.AUTO_PASS.value
        item["geometry"] = {
            "createdBy": geom.get("createdBy"),
            "insUnits": geom.get("insUnits"),
            "entityTypes": geom.get("entityTypes"),
            "polylineCount": geom.get("polylineCount"),
            "vertexCount": geom.get("vertexCount"),
            "boundingBox": geom.get("boundingBox"),
            "zValuesPresent": geom.get("zValuesPresent"),
        }
        results.append(item)
    return results
