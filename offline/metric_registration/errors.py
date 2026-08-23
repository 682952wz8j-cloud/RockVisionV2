from __future__ import annotations

import math

import numpy as np


def error_stats(residuals_xyz: np.ndarray) -> dict:
    res = np.asarray(residuals_xyz, dtype=float).reshape(-1, 3)
    if len(res) == 0:
        return {
            "count": 0,
            "median": None,
            "mean": None,
            "p90": None,
            "max": None,
            "min": None,
            "rmse": None,
            "horizontal": {"median": None, "p90": None, "max": None},
            "vertical": {"median": None, "p90": None, "max": None},
        }
    d3 = np.linalg.norm(res, axis=1)
    horiz = np.linalg.norm(res[:, :2], axis=1)
    vert = np.abs(res[:, 2])

    def pack(vals: np.ndarray) -> dict:
        ordered = np.sort(vals)
        return {
            "min": float(ordered[0]),
            "median": float(np.median(ordered)),
            "mean": float(vals.mean()),
            "p90": float(np.percentile(ordered, 90)),
            "max": float(ordered[-1]),
            "rmse": float(math.sqrt(np.mean(vals**2))),
        }

    three = pack(d3)
    three["horizontal"] = {k: pack(horiz)[k] for k in ("median", "p90", "max")}
    three["vertical"] = {k: pack(vert)[k] for k in ("median", "p90", "max")}
    three["count"] = int(len(res))
    return three
