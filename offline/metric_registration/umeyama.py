"""Umeyama similarity (Sim(3)) and application.

X_target = s * R * X_source + t
R is a proper rotation (det +1). Reflection is rejected, not silently flipped
beyond the standard Umeyama sign correction on the SVD.
"""

from __future__ import annotations

import math

import numpy as np

MIN_POINTS = 3


class Sim3Error(ValueError):
    pass


def _spatial_rank(centered: np.ndarray, rel_tol: float = 1e-8) -> int:
    singular = np.linalg.svd(centered, compute_uv=False)
    if len(singular) == 0 or singular[0] <= 0:
        return 0
    return int(np.sum(singular > rel_tol * singular[0]))


def invert_sim3(scale: float, rotation: np.ndarray, translation: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Inverse of X' = s R X + t  is  X = (1/s) R^T (X' - t)."""
    rotation = np.asarray(rotation, dtype=float).reshape(3, 3)
    translation = np.asarray(translation, dtype=float).reshape(3)
    inv_scale = 1.0 / float(scale)
    inv_rotation = rotation.T
    inv_translation = -inv_scale * inv_rotation @ translation
    return inv_scale, inv_rotation, inv_translation


def umeyama(source: np.ndarray, target: np.ndarray) -> dict:
    src = np.asarray(source, dtype=float).reshape(-1, 3)
    dst = np.asarray(target, dtype=float).reshape(-1, 3)
    if src.shape != dst.shape or len(src) < MIN_POINTS:
        raise Sim3Error(f"need at least {MIN_POINTS} paired 3D points, got {len(src)}")
    if not np.all(np.isfinite(src)) or not np.all(np.isfinite(dst)):
        raise Sim3Error("non-finite coordinates")

    n = len(src)
    mu_s = src.mean(axis=0)
    mu_d = dst.mean(axis=0)
    src_c = src - mu_s
    dst_c = dst - mu_d
    var_s = float(np.sum(src_c**2) / n)
    if var_s < 1e-18:
        raise Sim3Error("source points are degenerate (zero variance)")
    if _spatial_rank(src_c) < 2 or _spatial_rank(dst_c) < 2:
        raise Sim3Error("degenerate/near-collinear points")

    cov = (dst_c.T @ src_c) / n
    u, singular, vt = np.linalg.svd(cov)
    fix = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        fix[2, 2] = -1.0
    rotation = u @ fix @ vt
    det = float(np.linalg.det(rotation))
    if det < 0:
        raise Sim3Error("Umeyama produced a reflection; rejected")
    scale = float(np.sum(singular * np.diag(fix)) / var_s)
    if not math.isfinite(scale) or scale <= 0:
        raise Sim3Error(f"invalid scale {scale}")
    translation = mu_d - scale * rotation @ mu_s
    return {
        "scale": scale,
        "rotation": rotation,
        "translation": translation,
        "det": det,
        "orthoResidual": float(np.linalg.norm(rotation.T @ rotation - np.eye(3))),
    }


def apply_sim3(points: np.ndarray, scale: float, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    return scale * (np.asarray(rotation, dtype=float).reshape(3, 3) @ pts.T).T + np.asarray(
        translation, dtype=float
    ).reshape(3)


def residuals(source: np.ndarray, target: np.ndarray, scale: float, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    pred = apply_sim3(source, scale, rotation, translation)
    return np.asarray(target, dtype=float).reshape(-1, 3) - pred


def is_proper_rotation(rotation: np.ndarray, atol: float = 1e-6) -> bool:
    r = np.asarray(rotation, dtype=float).reshape(3, 3)
    return (
        abs(float(np.linalg.det(r)) - 1.0) <= atol
        and float(np.linalg.norm(r.T @ r - np.eye(3))) <= atol
    )


def rotation_quaternion_wxyz(rotation: np.ndarray) -> list[float]:
    r = np.asarray(rotation, dtype=float).reshape(3, 3)
    trace = float(np.trace(r))
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (r[2, 1] - r[1, 2]) / s
        y = (r[0, 2] - r[2, 0]) / s
        z = (r[1, 0] - r[0, 1]) / s
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2.0
        w = (r[2, 1] - r[1, 2]) / s
        x = 0.25 * s
        y = (r[0, 1] + r[1, 0]) / s
        z = (r[0, 2] + r[2, 0]) / s
    elif r[1, 1] > r[2, 2]:
        s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2.0
        w = (r[0, 2] - r[2, 0]) / s
        x = (r[0, 1] + r[1, 0]) / s
        y = 0.25 * s
        z = (r[1, 2] + r[2, 1]) / s
    else:
        s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2.0
        w = (r[1, 0] - r[0, 1]) / s
        x = (r[0, 2] + r[2, 0]) / s
        y = (r[1, 2] + r[2, 1]) / s
        z = 0.25 * s
    quat = np.array([w, x, y, z], dtype=float)
    quat = quat / np.linalg.norm(quat)
    if quat[0] < 0:
        quat = -quat
    return quat.tolist()


def rotation_axis_angle(rotation: np.ndarray) -> dict:
    r = np.asarray(rotation, dtype=float).reshape(3, 3)
    cos_t = max(-1.0, min(1.0, (float(np.trace(r)) - 1.0) / 2.0))
    angle = math.acos(cos_t)
    if angle < 1e-12:
        axis = [1.0, 0.0, 0.0]
    else:
        axis = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]], dtype=float)
        n = np.linalg.norm(axis)
        axis = (axis / n).tolist() if n > 0 else [1.0, 0.0, 0.0]
    return {"axis": axis, "angleRad": angle, "angleDeg": math.degrees(angle)}


def matrix4x4_row_major(scale: float, rotation: np.ndarray, translation: np.ndarray) -> list[list[float]]:
    r = scale * np.asarray(rotation, dtype=float).reshape(3, 3)
    t = np.asarray(translation, dtype=float).reshape(3)
    mat = np.eye(4)
    mat[:3, :3] = r
    mat[:3, 3] = t
    return mat.tolist()
