"""Select the 2026-08-23 DJI originalCameraImage set from qualification."""

from __future__ import annotations

import json
from pathlib import Path

from .layout import (
    DJI_CAPTURE_DIR,
    REQUIRED_SESSION,
    is_new_dji_relative,
    normalize_wall_relative,
    wall_incoming,
)

EXCLUDED_SESSIONS = {
    "legacy_dji_20260811",
    "legacy_terra_rtk_20260812",
    "iphone_20260823",
    "iphone_other",
    "not_a_capture",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def select_source_images(
    source_images: dict,
    associations: list[dict],
    incoming_wall: Path,
) -> tuple[list[dict], list[str]]:
    files = source_images.get("files") or []
    assoc_by_name = {}
    for item in associations:
        image_path = item.get("image") or ""
        assoc_by_name[Path(image_path).name] = item

    selected: list[dict] = []
    errors: list[str] = []
    for image in files:
        if image.get("captureSession") != REQUIRED_SESSION:
            continue
        if image.get("role") != "originalCameraImage":
            errors.append(f"{image.get('filename')} is {REQUIRED_SESSION} but role={image.get('role')}")
            continue
        raw_rel = image.get("relativePath") or ""
        if not is_new_dji_relative(raw_rel):
            errors.append(f"{image.get('filename')} session is {REQUIRED_SESSION} but path is not the 0823 DJI folder: {raw_rel}")
            continue
        rel = normalize_wall_relative(raw_rel)
        path = incoming_wall / rel
        if not path.is_file():
            errors.append(f"source image missing under wall incoming: {rel}")
            continue
        name = image.get("filename") or path.name
        assoc = assoc_by_name.get(name) or {}
        mrk = assoc.get("mrkNearest") if isinstance(assoc.get("mrkNearest"), dict) else {}
        selected.append(
            {
                "relativePath": rel,
                "qualificationRelativePath": raw_rel,
                "filename": name,
                "captureSession": REQUIRED_SESSION,
                "sourceDevice": image.get("sourceDevice"),
                "camera": {
                    "make": image.get("cameraMake"),
                    "model": image.get("cameraModel"),
                    "width": (image.get("dimensions") or {}).get("width"),
                    "height": (image.get("dimensions") or {}).get("height"),
                    "focalLength": image.get("focalLength"),
                    "focalLength35mm": image.get("focalLength35mm"),
                },
                "timestamp": image.get("captureTimestamp"),
                "mrkPhotoId": mrk.get("photoId") if mrk else "missing",
                "mrkAssociationStatus": (assoc.get("association") or {}).get("status") or "missing",
                "mrkMatched": bool(assoc.get("matchedMrk")),
                "colmapSourceCandidate": bool(image.get("colmapSourceCandidate")),
                "sha256Incoming": None,
            }
        )

    if any(row["captureSession"] != REQUIRED_SESSION for row in selected):
        errors.append("session isolation failed: non-0823 DJI images entered the source set")

    selected.sort(key=lambda row: (row["timestamp"] or "", row["filename"]))
    if len(selected) != 47:
        errors.append(f"expected 47 2026-08-23 DJI originals, selected {len(selected)}")
    if any(row["mrkAssociationStatus"] != "PROVEN" for row in selected) and selected:
        errors.append("one or more selected images do not have PROVEN MRK association")
    return selected, errors


def build_manifest(
    *,
    wall_id: str,
    selected: list[dict],
    incoming_wall: Path,
    camera_model: dict,
    sha256_by_rel: dict[str, str] | None = None,
    capture_session: str | None = None,
    source_folder: str | None = None,
) -> dict:
    rows = []
    for row in selected:
        item = dict(row)
        if sha256_by_rel:
            item["sha256Incoming"] = sha256_by_rel.get(item["relativePath"], row.get("sha256Incoming"))
        rows.append(item)
    return {
        "schemaVersion": "colmap.1",
        "wallId": wall_id,
        "captureSession": capture_session if capture_session is not None else REQUIRED_SESSION,
        "sourceFolder": source_folder if source_folder is not None else DJI_CAPTURE_DIR,
        "incomingRoot": str(incoming_wall),
        "imageCount": len(rows),
        "excluded": [
            "legacy_dji_20260811",
            "legacy_terra_derived",
            "iphone_20260823",
            "png_tiles",
            "tiff",
            "textures",
            "report_screenshots",
        ],
        "cameraModel": camera_model,
        "sWallColmap": "NOT COMPUTED",
        "outputFrame": "WallLocal",
        "wallMetricMetersProvenance": "NOT_CLAIMED",
        "images": rows,
    }


def qualification_paths(root: Path, wall_id: str) -> tuple[Path, Path]:
    dest = root / "offline" / "work" / wall_id / "qualification"
    return dest / "source_images.json", dest / "camera_georeference.json"


def load_and_select(root: Path, wall_id: str) -> tuple[list[dict], list[str], dict]:
    source_path, assoc_path = qualification_paths(root, wall_id)
    errors: list[str] = []
    if not source_path.is_file():
        return [], [f"missing {source_path}"], {}
    if not assoc_path.is_file():
        return [], [f"missing {assoc_path}"], {}
    source_images = load_json(source_path)
    associations = load_json(assoc_path)
    incoming = wall_incoming(root, wall_id)
    selected, select_errors = select_source_images(source_images, associations, incoming)
    errors.extend(select_errors)
    return selected, errors, source_images
