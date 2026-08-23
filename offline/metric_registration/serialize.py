from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .umeyama import matrix4x4_row_major, rotation_axis_angle, rotation_quaternion_wxyz


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(str(row.get(h, "")) for h in headers))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sim3_payload(
    *,
    scale: float,
    rotation: np.ndarray,
    translation: np.ndarray,
    origin: dict,
    fit_count: int,
    holdout_count: int,
    inlier_count: int,
    threshold_m: float,
    fit_metrics: dict,
    holdout_metrics: dict,
    solver_meta: dict,
) -> dict:
    rotation = np.asarray(rotation, dtype=float).reshape(3, 3)
    translation = np.asarray(translation, dtype=float).reshape(3)
    return {
        "schemaVersion": "S_wall_colmap.1",
        "name": "S_wall_colmap",
        "status": "computed",
        "sourceFrame": "colmap_reconstruction_rhs_opencv_units",
        "targetFrame": "wall_local_metres",
        "convention": "X_wall = s * R * X_colmap + t  (column vectors)",
        "units": {"source": "arbitrary_reconstruction_units", "target": "meters", "scale": "meters_per_colmap_unit"},
        "scale": float(scale),
        "rotationMatrix": {
            "layout": "row-major 3x3",
            "values": rotation.tolist(),
        },
        "quaternion": {
            "order": "wxyz",
            "values": rotation_quaternion_wxyz(rotation),
        },
        "axisAngle": rotation_axis_angle(rotation),
        "translationMeters": translation.tolist(),
        "matrix4x4": {
            "layout": "row-major",
            "vector": "column 4-vector [x,y,z,1]",
            "action": "X_wall_h = M * X_colmap_h",
            "values": matrix4x4_row_major(scale, rotation, translation),
        },
        "wallLocalOrigin": {
            "values": origin.get("origin"),
            "source": origin.get("source"),
            "relativePath": origin.get("relativePath"),
            "srs": origin.get("srs"),
            "note": "WallLocal = (UTM_E - E0, UTM_N - N0, Ellh - H0). Translation only.",
        },
        "wallLocalOriginSource": "metadata.xml SRSOrigin re-read from incoming",
        "coordinateConvention": {
            "colmapPose": "x_cam = R * x_world + t; camera_center = -R^T t",
            "mrkHeight": "ellipsoidal",
            "projectedMetric": "EPSG:32650 easting/northing + MRK Ellh (not a full 3D EPSG:32650 CRS)",
            "wallLocal": "metres relative to SRSOrigin; no axis swap or ENU rotation applied",
        },
        "fitImageCount": fit_count,
        "holdoutImageCount": holdout_count,
        "inlierImageCount": inlier_count,
        "inlierThresholdMeters": threshold_m,
        "fitMetrics": fit_metrics,
        "holdoutMetrics": holdout_metrics,
        "solver": "Umeyama 1991 similarity",
        "robustMethod": f"RANSAC + Umeyama refit, seed={solver_meta.get('seed')}, iters={solver_meta.get('iterations')}",
        "createdFrom": {
            "captureSession": "dji_20260823",
            "colmapSparse": "offline/work/wall_jiulongfeng_01/colmap/sparse/0",
            "mrk": "DJI_202608231218_006_九龙峰/DJI_20260823122214_0002_D.MRK",
            "gpsRuntimeUse": "offline Sim(3) only; GPS must not enter future visual localization / PnP",
        },
        "sWallColmapRuntimeNote": "Future iPhone pose is T_opencvCam_colmap in reconstruction units until this Sim(3) is applied offline to landmarks/routes.",
    }


def load_sim3(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = [
        "sourceFrame",
        "targetFrame",
        "scale",
        "rotationMatrix",
        "translationMeters",
        "matrix4x4",
        "convention",
    ]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"S_wall_colmap.json missing {missing}")
    return payload
