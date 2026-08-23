"""RANSAC + Umeyama refinement. Holdout points must never be passed in."""

from __future__ import annotations

import math

import numpy as np

from .umeyama import Sim3Error, apply_sim3, residuals, umeyama

DEFAULT_INLIER_THRESHOLD_M = 1.0
DEFAULT_ITERS = 2000
DEFAULT_SAMPLE = 3
DEFAULT_SEED = 20260823
DEFAULT_MIN_INLIERS = 10


def ransac_umeyama(
    source: np.ndarray,
    target: np.ndarray,
    *,
    threshold_m: float = DEFAULT_INLIER_THRESHOLD_M,
    iterations: int = DEFAULT_ITERS,
    sample_size: int = DEFAULT_SAMPLE,
    seed: int = DEFAULT_SEED,
    min_inliers: int = DEFAULT_MIN_INLIERS,
    used_ids: list | None = None,
) -> dict:
    src = np.asarray(source, dtype=float).reshape(-1, 3)
    dst = np.asarray(target, dtype=float).reshape(-1, 3)
    if len(src) != len(dst):
        raise Sim3Error("source/target count mismatch")
    if len(src) < sample_size:
        raise Sim3Error("not enough points for robust Sim(3)")

    rng = np.random.default_rng(seed)
    best = None
    for _ in range(iterations):
        idx = rng.choice(len(src), size=sample_size, replace=False)
        if used_ids is not None:
            used_ids.extend(int(i) for i in idx)
        try:
            est = umeyama(src[idx], dst[idx])
        except Sim3Error:
            continue
        err = np.linalg.norm(residuals(src, dst, est["scale"], est["rotation"], est["translation"]), axis=1)
        inliers = np.where(err <= threshold_m)[0]
        if len(inliers) == 0:
            continue
        if best is None or len(inliers) > len(best["inliers"]) or (
            len(inliers) == len(best["inliers"]) and float(np.median(err[inliers])) < best["medianInlier"]
        ):
            best = {
                "inliers": inliers,
                "estimate": est,
                "medianInlier": float(np.median(err[inliers])) if len(inliers) else math.inf,
            }

    if best is None or len(best["inliers"]) < min_inliers:
        raise Sim3Error(
            f"robust Sim(3) failed: inliers={0 if best is None else len(best['inliers'])} "
            f"min_required={min_inliers} threshold={threshold_m}m"
        )

    inliers = np.array(sorted(int(i) for i in best["inliers"]))
    refined = umeyama(src[inliers], dst[inliers])
    all_err = np.linalg.norm(residuals(src, dst, refined["scale"], refined["rotation"], refined["translation"]), axis=1)
    inliers = np.where(all_err <= threshold_m)[0]
    if len(inliers) >= sample_size:
        refined = umeyama(src[inliers], dst[inliers])
        all_err = np.linalg.norm(residuals(src, dst, refined["scale"], refined["rotation"], refined["translation"]), axis=1)
        inliers = np.where(all_err <= threshold_m)[0]
    outliers = np.array([i for i in range(len(src)) if i not in set(inliers)], dtype=int)
    return {
        "scale": refined["scale"],
        "rotation": refined["rotation"],
        "translation": refined["translation"],
        "det": refined["det"],
        "orthoResidual": refined["orthoResidual"],
        "inlierIndices": inliers.tolist(),
        "outlierIndices": outliers.tolist(),
        "inlierCount": int(len(inliers)),
        "outlierCount": int(len(outliers)),
        "thresholdM": threshold_m,
        "iterations": iterations,
        "seed": seed,
        "errorsM": all_err.tolist(),
    }
