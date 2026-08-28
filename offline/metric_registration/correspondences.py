"""Deterministic COLMAP camera ↔ MRK correspondences for dji_20260823."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from offline.colmap.layout import DJI_CAPTURE_DIR, REQUIRED_SESSION
from offline.qualification.associate import dji_filename_parts
from offline.qualification.rtk import parse_mrk

from .frames import (
    METADATA_XML,
    UTM_EPSG,
    camera_center_from_world_to_camera,
    geodetic_to_projected_metric,
    read_srs_origin,
    to_wall_local,
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def colmap_camera_centers(reconstruction) -> dict[str, dict]:
    out = {}
    for image_id in reconstruction.reg_image_ids():
        image = reconstruction.image(image_id)
        pose = image.cam_from_world()
        matrix = np.asarray(pose.matrix(), dtype=float)
        rotation = matrix[:3, :3]
        translation = np.asarray(pose.translation, dtype=float).reshape(3)
        center = camera_center_from_world_to_camera(rotation, translation)
        out[image.name] = {
            "colmapImageId": int(image_id),
            "filename": image.name,
            "rotation": rotation.tolist(),
            "translation": translation.tolist(),
            "center": center.tolist(),
        }
    return out


def load_mrk_by_photo_id(mrk_path: Path) -> dict[int, dict]:
    parsed = parse_mrk(mrk_path.read_text(encoding="utf-8", errors="replace"))
    by_id = {}
    for rec in parsed.get("records") or []:
        photo_id = rec.get("photoId")
        if isinstance(photo_id, int):
            by_id[photo_id] = rec
    return by_id


def build_correspondences(
    *,
    manifest: dict,
    reconstruction,
    incoming_wall: Path,
    mrk_relative_path: str | None = None,
    metadata_relative_path: str | None = None,
    require_legacy_session: bool = True,
    association_method: str | None = None,
) -> tuple[list[dict], list[str], dict]:
    errors: list[str] = []
    if require_legacy_session and manifest.get("captureSession") != REQUIRED_SESSION:
        errors.append(f"manifest session is {manifest.get('captureSession')}, expected {REQUIRED_SESSION}")
    meta_rel = metadata_relative_path or METADATA_XML
    origin_info = read_srs_origin(incoming_wall / meta_rel, relative_path=meta_rel)
    origin = np.array(origin_info["origin"], dtype=float)
    if origin_info["srs"] != UTM_EPSG:
        errors.append(f"metadata.xml SRS is {origin_info['srs']}, expected {UTM_EPSG}")

    centers = colmap_camera_centers(reconstruction)
    mrk_rel = mrk_relative_path or str(Path(DJI_CAPTURE_DIR) / "DJI_20260823122214_0002_D.MRK")
    mrk_path = incoming_wall / mrk_rel
    if not mrk_path.is_file():
        return [], [f"missing MRK {mrk_path}"], origin_info
    mrk_by_id = load_mrk_by_photo_id(mrk_path)
    method = association_method or (
        "filename_sequence==MRK.photoId + captureSession dji_20260823"
        if require_legacy_session
        else "filename_sequence==MRK.photoId + same_parent_directory"
    )

    rows = []
    for image in manifest.get("images") or []:
        if require_legacy_session and image.get("captureSession") != REQUIRED_SESSION:
            errors.append(f"{image.get('filename')} is not {REQUIRED_SESSION}")
            continue
        name = image["filename"]
        parts = dji_filename_parts(name)
        if not parts:
            errors.append(f"{name} is not a DJI filename")
            continue
        photo_id = parts["sequence"]
        if image.get("mrkPhotoId") != photo_id:
            errors.append(f"{name} manifest mrkPhotoId={image.get('mrkPhotoId')} != filename sequence {photo_id}")
            continue
        if image.get("mrkAssociationStatus") != "PROVEN":
            errors.append(f"{name} MRK association is {image.get('mrkAssociationStatus')}")
            continue
        if name not in centers:
            errors.append(f"{name} is not a registered COLMAP camera")
            continue
        rec = mrk_by_id.get(photo_id)
        if rec is None:
            errors.append(f"{name} has no MRK record photoId={photo_id}")
            continue
        metric = geodetic_to_projected_metric(rec["latitude"], rec["longitude"], rec["ellipsoidalHeight"])
        local = to_wall_local(metric, origin)
        rows.append(
            {
                "filename": name,
                "relativePath": image["relativePath"],
                "captureSession": image.get("captureSession"),
                "mrkPhotoId": photo_id,
                "associationMethod": method,
                "colmapImageId": centers[name]["colmapImageId"],
                "colmapCenter": centers[name]["center"],
                "mrk": {
                    "latitude": rec["latitude"],
                    "longitude": rec["longitude"],
                    "ellipsoidalHeight": rec["ellipsoidalHeight"],
                    "heightDatum": "ellipsoidal",
                    "sourceFile": mrk_rel,
                },
                "projectedMetric": {
                    "easting": float(metric[0]),
                    "northing": float(metric[1]),
                    "ellipsoidalHeight": float(metric[2]),
                    "horizontalCrs": UTM_EPSG,
                    "note": "Z is MRK Ellh, not a complete 3D EPSG:32650 CRS.",
                },
                "wallLocal": local.tolist(),
            }
        )

    rows.sort(key=lambda item: (item["mrkPhotoId"], item["filename"]))
    origin_info = {**origin_info, "origin": origin.tolist()}
    return rows, errors, origin_info
