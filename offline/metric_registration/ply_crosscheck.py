"""PLY is a post-fit sanity check only. It must never enter Sim(3) estimation."""

from __future__ import annotations

import math
import struct
from collections import defaultdict
from pathlib import Path

import numpy as np

from offline.qualification.ply_stats import read_ply_header, read_ply_xyz

PLY_RELATIVE = "九龙峰森林站大楼/models/pc/0/terra_ply/BlockR/BlockR.ply"


def write_xyz_ply(path: Path, points: np.ndarray) -> None:
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"comment RockVision transformed COLMAP points3D in WallLocal metres\n"
        f"element vertex {len(pts)}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
    ).encode("ascii")
    with path.open("wb") as handle:
        handle.write(header)
        handle.write(pts.tobytes(order="C"))


def landmark_sanity(points: np.ndarray) -> dict:
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    finite = bool(np.all(np.isfinite(pts)))
    mins = pts.min(axis=0) if len(pts) else np.zeros(3)
    maxs = pts.max(axis=0) if len(pts) else np.zeros(3)
    extent = maxs - mins
    span = float(np.linalg.norm(extent)) if len(pts) else 0.0
    explosion = span > 5000.0 or float(np.max(np.abs(pts))) > 10000.0
    return {
        "count": int(len(pts)),
        "finite": finite,
        "hasNan": bool(np.isnan(pts).any()),
        "hasInf": bool(np.isinf(pts).any()),
        "bboxMin": mins.tolist(),
        "bboxMax": maxs.tolist(),
        "extent": extent.tolist(),
        "span": span,
        "kilometerScaleExplosion": explosion,
    }


def nearest_expanding(
    queries: np.ndarray,
    cloud: np.ndarray,
    *,
    cell: float = 5.0,
    max_radius_m: float = 80.0,
) -> dict:
    q = np.asarray(queries, dtype=float).reshape(-1, 3)
    c = np.asarray(cloud, dtype=float).reshape(-1, 3)
    if len(q) == 0 or len(c) == 0:
        return {"status": "missing", "reason": "no query or cloud points"}
    try:
        from scipy.spatial import cKDTree

        tree = cKDTree(c)
        distances, _ = tree.query(q, k=1, workers=-1)
        distances = np.asarray(distances, dtype=float)
        method = "scipy.spatial.cKDTree"
    except Exception:
        distances = _grid_nearest(q, c, cell=cell, max_radius_m=max_radius_m)
        method = "expanding_grid"
    finite = np.where(np.isfinite(distances), distances, np.nan)
    beyond = int(np.sum(~np.isfinite(finite) | (finite > max_radius_m)))
    ordered = np.sort(finite[np.isfinite(finite)])
    return {
        "status": "ok",
        "count": int(len(ordered)),
        "min": float(ordered[0]),
        "median": float(np.median(ordered)),
        "p90": float(np.percentile(ordered, 90)),
        "max": float(ordered[-1]),
        "cellMeters": cell,
        "maxSearchRadiusM": max_radius_m,
        "cappedAtMaxRadius": beyond,
        "method": method,
        "note": (
            "Sparse COLMAP landmarks include vegetation/background/roof; "
            "this is a spatial-overlap cross-check, not a fit residual. "
            "PLY vertices were not used to estimate Sim(3)."
        ),
    }


def _grid_nearest(queries: np.ndarray, cloud: np.ndarray, *, cell: float, max_radius_m: float) -> np.ndarray:
    grid: dict[tuple[int, int, int], list[np.ndarray]] = defaultdict(list)
    for point in cloud:
        key = (
            math.floor(point[0] / cell),
            math.floor(point[1] / cell),
            math.floor(point[2] / cell),
        )
        grid[key].append(point)
    distances = []
    max_ring = max(1, int(math.ceil(max_radius_m / cell)))
    for point in queries:
        gx, gy, gz = (
            math.floor(point[0] / cell),
            math.floor(point[1] / cell),
            math.floor(point[2] / cell),
        )
        best = math.inf
        for ring in range(max_ring + 1):
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    for dz in range(-ring, ring + 1):
                        if max(abs(dx), abs(dy), abs(dz)) != ring:
                            continue
                        for other in grid.get((gx + dx, gy + dy, gz + dz), ()):
                            dist = float(np.linalg.norm(other - point))
                            if dist < best:
                                best = dist
            if best < math.inf and best <= (ring + 1) * cell * math.sqrt(3):
                break
        distances.append(best)
    return np.asarray(distances, dtype=float)


def load_existing_ply(incoming_wall: Path, relative_path: str | None = None) -> tuple[np.ndarray, dict]:
    rel = relative_path or PLY_RELATIVE
    path = incoming_wall / rel
    header = read_ply_header(path)
    points = np.asarray(read_ply_xyz(path, header), dtype=float)
    return points, {"relativePath": rel, "header": header, "count": int(len(points))}
