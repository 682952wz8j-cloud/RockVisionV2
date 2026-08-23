"""Coordinate frames for metric registration.

Frames
------
C  COLMAP reconstruction. Camera pose is world-to-camera:
       x_cam = R * x_world + t
   camera center C = -R^T t

G  Geodetic WGS-84 geographic from 2026-08-23 DJI MRK:
       (latitude, longitude, Ellh)
   Ellh is ellipsoidal height, not orthometric / MSL / local Z.

M  Projected metric triplet used for this gate only:
       (UTM easting EPSG:32650, UTM northing EPSG:32650, Ellh)
   This is not a complete 3D EPSG:32650 CRS; Z is MRK Ellh.

W  WallLocal metres:
       X = Easting  - Origin_E
       Y = Northing - Origin_N
       Z = Ellh     - Origin_H
   Translation only. No axis swap, ENU rotation, or extra R.
"""

from __future__ import annotations

import math
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

from offline.qualification.geodesy import geographic_to_utm

UTM_ZONE = 50
UTM_EPSG = "EPSG:32650"
HEIGHT_DATUM = "ellipsoidal"
METADATA_XML = "九龙峰森林站大楼/models/pc/0/terra_ply/metadata.xml"


def camera_center_from_world_to_camera(rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    """COLMAP stores x_cam = R x_world + t. Center is C = -R^T t."""
    rotation = np.asarray(rotation, dtype=float).reshape(3, 3)
    translation = np.asarray(translation, dtype=float).reshape(3)
    return -rotation.T @ translation


def rotation_from_matrix4(matrix: np.ndarray) -> np.ndarray:
    return np.asarray(matrix, dtype=float).reshape(4, 4)[:3, :3]


def translation_from_matrix4(matrix: np.ndarray) -> np.ndarray:
    return np.asarray(matrix, dtype=float).reshape(4, 4)[:3, 3]


def geodetic_to_projected_metric(lat_deg: float, lon_deg: float, ellipsoidal_height: float) -> np.ndarray:
    easting, northing = geographic_to_utm(lat_deg, lon_deg, UTM_ZONE)
    return np.array([easting, northing, float(ellipsoidal_height)], dtype=float)


def to_wall_local(metric: np.ndarray, origin: np.ndarray) -> np.ndarray:
    return np.asarray(metric, dtype=float).reshape(3) - np.asarray(origin, dtype=float).reshape(3)


def from_wall_local(local: np.ndarray, origin: np.ndarray) -> np.ndarray:
    return np.asarray(local, dtype=float).reshape(3) + np.asarray(origin, dtype=float).reshape(3)


def read_srs_origin(metadata_xml: Path) -> dict:
    tree = ET.parse(metadata_xml)
    root = tree.getroot()
    srs = (root.findtext("SRS") or "").strip()
    text = (root.findtext("SRSOrigin") or "").strip()
    parts = [float(p) for p in text.split(",") if p.strip()]
    if len(parts) != 3:
        raise ValueError(f"SRSOrigin is not 3 numbers: {text!r}")
    return {
        "srs": srs,
        "srsOriginText": text,
        "origin": parts,
        "relativePath": METADATA_XML,
        "source": str(metadata_xml),
    }


def origin_compatible_with_mrk(origin: np.ndarray, metrics: list[np.ndarray], max_offset_m: float = 250.0) -> dict:
    arr = np.asarray(metrics, dtype=float).reshape(-1, 3)
    deltas = arr - np.asarray(origin, dtype=float).reshape(3)
    offset = np.linalg.norm(deltas, axis=1)
    return {
        "compatible": bool(offset.max() <= max_offset_m),
        "minOffsetM": float(offset.min()),
        "maxOffsetM": float(offset.max()),
        "medianOffsetM": float(np.median(offset)),
        "maxAllowedM": max_offset_m,
    }


def pairwise_distances(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    diffs = pts[:, None, :] - pts[None, :, :]
    dist = np.linalg.norm(diffs, axis=2)
    iu = np.triu_indices(len(pts), k=1)
    return dist[iu]


def pointset_geometry(points: np.ndarray) -> dict:
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    mins = pts.min(axis=0)
    maxs = pts.max(axis=0)
    extent = maxs - mins
    pairwise = pairwise_distances(pts) if len(pts) >= 2 else np.array([])
    centered = pts - pts.mean(axis=0)
    if len(pts) >= 3:
        cov = centered.T @ centered / max(len(pts) - 1, 1)
        eig = np.sort(np.linalg.eigvalsh(cov))[::-1]
        eig = np.clip(eig, 0.0, None)
    else:
        eig = np.zeros(3)
    span = float(np.linalg.norm(extent))
    smallest = float(extent.min())
    if len(pts) < 3 or span < 1e-6:
        status = "DEGENERATE"
        why = "Fewer than 3 distinct points or near-zero span."
    elif eig[0] > 0 and eig[1] / eig[0] < 0.01 and eig[2] / eig[0] < 0.01:
        status = "DEGENERATE"
        why = "Points are near-collinear; Sim(3) rotation/scale is poorly constrained."
    elif smallest < 1.0 or (eig[0] > 0 and eig[2] / eig[0] < 0.02):
        status = "WEAK"
        why = "Extent is thin or nearly planar; vertical/scale may be weakly constrained."
    elif smallest >= 5.0 and span >= 15.0:
        status = "GOOD"
        why = "Non-degenerate 3D volume with multi-metre extent on all axes."
    else:
        status = "ACCEPTABLE"
        why = "Not collapsed to a point or line; volume is usable but compact."
    return {
        "count": int(len(pts)),
        "bboxMin": mins.tolist(),
        "bboxMax": maxs.tolist(),
        "extent": extent.tolist(),
        "span": span,
        "pairwise": {
            "min": float(pairwise.min()) if len(pairwise) else None,
            "median": float(np.median(pairwise)) if len(pairwise) else None,
            "max": float(pairwise.max()) if len(pairwise) else None,
        },
        "eigenvalues": eig.tolist(),
        "status": status,
        "reason": why,
    }


def combine_conditioning(colmap_geom: dict, wall_geom: dict) -> dict:
    rank = {"DEGENERATE": 0, "WEAK": 1, "ACCEPTABLE": 2, "GOOD": 3}
    status = min([colmap_geom["status"], wall_geom["status"]], key=lambda s: rank[s])
    return {
        "status": status,
        "colmap": colmap_geom,
        "wallLocal": wall_geom,
        "reason": f"COLMAP {colmap_geom['status']}: {colmap_geom['reason']} WallLocal {wall_geom['status']}: {wall_geom['reason']}",
    }
