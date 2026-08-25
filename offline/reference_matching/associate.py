"""OpenCV keypoint ↔ COLMAP reconstructed observation association v1.

Only image-space (x, y), nearest-neighbor distance, mutual nearest, uniqueness.
No descriptor, scale, octave, or orientation.
Each OpenCV keypoint gets one exclusive reason.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from .constants import MAX_PIXEL_DISTANCE

REASON_ACCEPTED = "accepted"
REASON_NO_2PX = "no_2px_neighbor"
REASON_NOT_MUTUAL = "not_mutual"
REASON_UNIQUENESS = "uniqueness"


@dataclass
class AssociationResult:
    opencv_index: np.ndarray
    colmap_index: np.ndarray
    distance: np.ndarray
    nearest_distance: np.ndarray
    reason: np.ndarray
    accepted_mask: np.ndarray


def _histogram(nearest: np.ndarray) -> dict[str, int]:
    finite = nearest[np.isfinite(nearest)]
    inf_count = int(np.size(nearest) - np.size(finite))
    return {
        "0_1": int(np.sum((finite >= 0) & (finite < 1.0))),
        "1_2": int(np.sum((finite >= 1.0) & (finite < 2.0))),
        "2_3": int(np.sum((finite >= 2.0) & (finite < 3.0))),
        "3_5": int(np.sum((finite >= 3.0) & (finite < 5.0))),
        "gt_5": int(np.sum(finite >= 5.0)),
        "noReconstructedNeighbor": inf_count,
    }


def associate_xy(
    opencv_xy: np.ndarray,
    colmap_xy: np.ndarray,
    max_pixel_distance: float = MAX_PIXEL_DISTANCE,
) -> AssociationResult:
    """Associate OpenCV keypoints to reconstructed (has Point3D) observations only.

    Reject order, exclusive:
    1. no reconstructed observation within max_pixel_distance
    2. not mutual nearest
    3. uniqueness: a second reconstructed observation also within the radius
    """
    opencv_xy = np.asarray(opencv_xy, dtype=np.float64).reshape(-1, 2)
    colmap_xy = np.asarray(colmap_xy, dtype=np.float64).reshape(-1, 2)
    n = len(opencv_xy)
    reasons = np.full(n, REASON_NO_2PX, dtype=object)
    nearest = np.full(n, np.inf, dtype=np.float64)
    partner = np.full(n, -1, dtype=np.int64)
    partner_dist = np.full(n, np.inf, dtype=np.float64)
    if n == 0:
        return AssociationResult(
            opencv_index=np.zeros(0, dtype=np.int64),
            colmap_index=np.zeros(0, dtype=np.int64),
            distance=np.zeros(0, dtype=np.float64),
            nearest_distance=nearest,
            reason=reasons,
            accepted_mask=np.zeros(0, dtype=bool),
        )
    if len(colmap_xy) == 0:
        return AssociationResult(
            opencv_index=np.zeros(0, dtype=np.int64),
            colmap_index=np.zeros(0, dtype=np.int64),
            distance=np.zeros(0, dtype=np.float64),
            nearest_distance=nearest,
            reason=reasons,
            accepted_mask=np.zeros(n, dtype=bool),
        )

    tree_c = cKDTree(colmap_xy)
    k = 2 if len(colmap_xy) >= 2 else 1
    nn_dist, nn_idx = tree_c.query(opencv_xy, k=k)
    nn_dist = np.asarray(nn_dist, dtype=np.float64)
    nn_idx = np.asarray(nn_idx, dtype=np.int64)
    if nn_dist.ndim == 1:
        nn_dist = nn_dist.reshape(-1, 1)
        nn_idx = nn_idx.reshape(-1, 1)
    if nn_dist.shape[1] == 1:
        nn_dist = np.concatenate([nn_dist, np.full((n, 1), np.inf)], axis=1)
        nn_idx = np.concatenate([nn_idx, np.full((n, 1), -1, dtype=np.int64)], axis=1)

    nearest[:] = nn_dist[:, 0]
    tree_o = cKDTree(opencv_xy)
    _rev_dist, rev_idx = tree_o.query(colmap_xy, k=1)
    rev_idx = np.asarray(rev_idx, dtype=np.int64).reshape(-1)

    for i in range(n):
        d1 = float(nn_dist[i, 0])
        j = int(nn_idx[i, 0])
        if not np.isfinite(d1) or d1 > max_pixel_distance:
            reasons[i] = REASON_NO_2PX
            continue
        if int(rev_idx[j]) != i:
            reasons[i] = REASON_NOT_MUTUAL
            continue
        d2 = float(nn_dist[i, 1])
        if np.isfinite(d2) and d2 <= max_pixel_distance:
            reasons[i] = REASON_UNIQUENESS
            continue
        reasons[i] = REASON_ACCEPTED
        partner[i] = j
        partner_dist[i] = d1

    accepted = reasons == REASON_ACCEPTED
    opencv_index = np.nonzero(accepted)[0].astype(np.int64)
    return AssociationResult(
        opencv_index=opencv_index,
        colmap_index=partner[accepted],
        distance=partner_dist[accepted],
        nearest_distance=nearest,
        reason=reasons,
        accepted_mask=accepted,
    )


def count_reasons(reason: np.ndarray) -> dict[str, int]:
    values, counts = np.unique(np.asarray(reason, dtype=object), return_counts=True)
    out = {
        REASON_ACCEPTED: 0,
        REASON_NO_2PX: 0,
        REASON_NOT_MUTUAL: 0,
        REASON_UNIQUENESS: 0,
    }
    for value, count in zip(values, counts):
        out[str(value)] = int(count)
    return out


def summarize_association(
    *,
    opencv_count: int,
    colmap_reconstructed: int,
    colmap_without_3d: int,
    result: AssociationResult,
    max_pixel_distance: float = MAX_PIXEL_DISTANCE,
) -> dict:
    buckets = count_reasons(result.reason)
    accepted = buckets[REASON_ACCEPTED]
    yield_frac = (accepted / opencv_count) if opencv_count else 0.0
    return {
        "maxPixelDistance": max_pixel_distance,
        "opencvFeaturesTotal": opencv_count,
        "colmapReconstructedObservations": colmap_reconstructed,
        "colmapPoints2DWithout3D": colmap_without_3d,
        "candidateAssociations": int(np.sum(result.nearest_distance <= max_pixel_distance)),
        "accepted": accepted,
        "mutualRejected": buckets[REASON_NOT_MUTUAL],
        "uniquenessRejected": buckets[REASON_UNIQUENESS],
        "twoPxRejected": buckets[REASON_NO_2PX],
        "no3DRejected": colmap_without_3d,
        "associationYield": yield_frac,
        "nearestDistanceHistogram": _histogram(result.nearest_distance),
        "reasonBucketsExclusive": True,
        "no3DNote": (
            "no3DRejected counts COLMAP points2D without POINT3D_ID. "
            "They are excluded from the neighbor set and from the 2px decision."
        ),
    }
