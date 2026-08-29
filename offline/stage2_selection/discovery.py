"""Read-only discovery of Stage 2 candidates. Never mutates incoming."""

from __future__ import annotations

from pathlib import Path

from offline.ingestion.detect import classify_file
from offline.ingestion.hashing import sha256_file
from offline.ingestion.images import image_to_json, inspect_image
from offline.qualification.associate import dji_filename_parts
from offline.qualification.images import classify_image, collect_ply_texture_names
from offline.qualification.metadata_scan import parse_model_metadata_xml
from offline.qualification.rtk import parse_mrk
from offline.stage2_selection.terra import has_exact_temp_component

_SKIP_NAMES = {".ds_store"}
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
_TILE_HINT = ("/tiles/", "/terra_b3dms/", "/overlap_render", "/screennail", "/report/")


def _rel(incoming: Path, path: Path) -> str:
    return path.relative_to(incoming).as_posix()


def _parent(rel: str) -> str:
    parent = Path(rel).parent.as_posix()
    return parent if parent != "." else "."


def iter_incoming_files(incoming: Path) -> list[Path]:
    files = [p for p in incoming.rglob("*") if p.is_file() and p.name.lower() not in _SKIP_NAMES]
    files.sort(key=lambda p: p.relative_to(incoming).as_posix())
    return files


def discover_candidates(incoming: Path) -> dict:
    files = iter_incoming_files(incoming)
    ply_paths = [p for p in files if p.suffix.lower() == ".ply"]
    textures: set[str] = set()
    for ply in ply_paths:
        textures |= collect_ply_texture_names(incoming, _rel(incoming, ply))

    images: list[dict] = []
    mrk_files: list[dict] = []
    capture_metadata: list[dict] = []
    model_spatial: list[dict] = []
    model_geometry: list[dict] = []
    at_metadata: list[dict] = []
    rejected: list[dict] = []

    for path in files:
        rel = _rel(incoming, path)
        ext = path.suffix.lower()
        name = path.name
        if ext in _IMAGE_EXT:
            skip_decode = ext == ".png" and any(hint in rel.replace("\\", "/").lower() for hint in _TILE_HINT)
            record = {
                "relativePath": rel,
                "filename": name,
                "extension": ext,
                "image": {},
            }
            if skip_decode:
                record["image"] = {
                    "pixelWidth": 256,
                    "pixelHeight": 256,
                    "cameraMake": "missing",
                    "cameraModel": "missing",
                    "captureTimestamp": "missing",
                    "gpsLatitude": "missing",
                    "gpsLongitude": "missing",
                    "gpsAltitude": "missing",
                    "hasExif": False,
                    "imageFormat": "PNG",
                    "software": "missing",
                    "orientation": "missing",
                    "lensModel": "missing",
                    "focalLength": "missing",
                    "focalLength35mm": "missing",
                }
            else:
                detected, _method, signature = classify_file(path)
                if detected.value == "image":
                    info, _status = inspect_image(path, signature)
                    record["image"] = image_to_json(info)
            classified = classify_image(record, textures)
            classified["sha256"] = sha256_file(path) if ext in {".jpg", ".jpeg"} else None
            classified["fileSize"] = path.stat().st_size
            images.append(classified)
            continue

        if ext == ".mrk":
            parsed = parse_mrk(path.read_text(encoding="utf-8", errors="replace"))
            parts = dji_filename_parts(name)
            mrk_files.append(
                {
                    "relativePath": rel,
                    "filename": name,
                    "parentDirectory": _parent(rel),
                    "sha256": sha256_file(path),
                    "fileType": parsed.get("fileType"),
                    "parseStatus": parsed.get("parseStatus"),
                    "recordCount": parsed.get("recordCount"),
                    "records": parsed.get("records") or [],
                    "mrkFilenameDate": parts["date"] if parts else None,
                    "photoIds": [
                        rec.get("photoId")
                        for rec in (parsed.get("records") or [])
                        if isinstance(rec.get("photoId"), int)
                    ],
                }
            )
            continue

        if name.lower() == "metadata.xml":
            if has_exact_temp_component(rel):
                continue
            parsed_xml = parse_model_metadata_xml(path)
            origin = (parsed_xml or {}).get("srsOrigin")
            origin_ok = isinstance(origin, list) and len(origin) == 3
            model_spatial.append(
                {
                    "relativePath": rel,
                    "filename": name,
                    "parentDirectory": _parent(rel),
                    "sha256": sha256_file(path),
                    "parseable": bool(parsed_xml),
                    "srs": (parsed_xml or {}).get("srs"),
                    "srsOrigin": origin if origin_ok else None,
                    "srsOriginText": (parsed_xml or {}).get("srsOriginText"),
                    "malformedOrigin": bool(parsed_xml) and not origin_ok,
                    "kind": "modelSpatialMetadata",
                    "proposedModelTreeEvidence": {
                        "rule": "same model-export tree / terra_ply adjacency",
                        "classification": "PROPOSED_GENERIC_RULE_REQUIRING_VALIDATION",
                        "terraPlyAdjacent": "/terra_ply/" in rel.replace("\\", "/").lower(),
                        "usedAsValidatedMethodRule": False,
                    },
                }
            )
            continue

        if ext == ".ply":
            if has_exact_temp_component(rel):
                continue
            model_geometry.append(
                {
                    "relativePath": rel,
                    "filename": name,
                    "parentDirectory": _parent(rel),
                    "sha256": sha256_file(path),
                    "kind": "modelGeometry",
                    "proposedModelTreeEvidence": {
                        "rule": "terra_ply adjacency",
                        "classification": "PROPOSED_GENERIC_RULE_REQUIRING_VALIDATION",
                        "terraPlyAdjacent": "/terra_ply/" in rel.replace("\\", "/").lower(),
                        "usedAsValidatedMethodRule": False,
                    },
                }
            )
            continue

        if name == "sfm_geo_desc.json" or "BlocksExchange" in name or "/AT/" in rel.replace("\\", "/"):
            at_metadata.append(
                {
                    "relativePath": rel,
                    "filename": name,
                    "kind": "atReconstructionMetadata",
                    "note": "AT/reconstruction metadata is not model spatial metadata.",
                }
            )
            continue

        if ext in {".xml", ".json"} and any(
            token in rel.replace("\\", "/").lower() for token in ("/at/", "sfm", "camera")
        ):
            capture_metadata.append(
                {
                    "relativePath": rel,
                    "filename": name,
                    "kind": "captureOrAtMetadata",
                }
            )

    return {
        "images": images,
        "mrkCandidates": mrk_files,
        "captureMetadataCandidates": capture_metadata,
        "modelSpatialMetadataCandidates": model_spatial,
        "modelCandidates": model_geometry,
        "atReconstructionMetadataCandidates": at_metadata,
        "rejectedCandidates": rejected,
    }
