"""COLMAP reconstruction observations. Geometry only — never descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


class ColmapGeometryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageObservations:
    image_id: int
    name: str
    width: int
    height: int
    xy: np.ndarray  # (M, 2) reconstructed observations only
    point3d_ids: np.ndarray  # (M,) int64
    colmap_xyz: np.ndarray  # (M, 3)
    points2d_total: int
    points2d_without_3d: int


def load_reconstruction(sparse_dir: Path):
    try:
        import pycolmap
    except ImportError as exc:
        raise ColmapGeometryError("pycolmap is required to read COLMAP sparse") from exc
    rec = pycolmap.Reconstruction()
    rec.read(str(sparse_dir))
    return rec


def _track_len(point) -> int:
    track = point.track
    if hasattr(track, "elements"):
        return len(track.elements)
    if hasattr(track, "__len__"):
        return len(track)
    return 0


def image_observations(reconstruction) -> list[ImageObservations]:
    out: list[ImageObservations] = []
    for image_id in reconstruction.reg_image_ids():
        image = reconstruction.images[image_id]
        camera = reconstruction.cameras[image.camera_id]
        xy: list[list[float]] = []
        pids: list[int] = []
        xyz: list[list[float]] = []
        without = 0
        total = len(image.points2D)
        for point in image.points2D:
            if not point.has_point3D():
                without += 1
                continue
            pid = int(point.point3D_id)
            landmark = reconstruction.points3D[pid]
            xy.append([float(point.xy[0]), float(point.xy[1])])
            pids.append(pid)
            xyz.append([float(landmark.xyz[0]), float(landmark.xyz[1]), float(landmark.xyz[2])])
        out.append(
            ImageObservations(
                image_id=int(image_id),
                name=str(image.name),
                width=int(camera.width),
                height=int(camera.height),
                xy=np.asarray(xy, dtype=np.float64).reshape(-1, 2),
                point3d_ids=np.asarray(pids, dtype=np.int64),
                colmap_xyz=np.asarray(xyz, dtype=np.float64).reshape(-1, 3),
                points2d_total=total,
                points2d_without_3d=without,
            )
        )
    return out


def point3d_track_lengths(reconstruction) -> dict[int, int]:
    return {int(pid): _track_len(pt) for pid, pt in reconstruction.points3D.items()}
