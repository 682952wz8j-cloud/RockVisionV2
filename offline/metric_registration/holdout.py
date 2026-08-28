"""Deterministic spatially interleaved holdout. Never the last contiguous 12."""

from __future__ import annotations


def split_fit_holdout(rows: list[dict], holdout_stride: int = 4) -> tuple[list[dict], list[dict]]:
    """Every 4th correspondence by photoId is holdout.

    Sorting is by MRK photoId (flight sequence). Taking indices 0,4,8,...
    interleaves holdout along the trajectory instead of taking one end.
    Holdout cardinality is a function of n_rows and stride, not a frozen 12/35.
    """
    ordered = sorted(rows, key=lambda item: (item["mrkPhotoId"], item["filename"]))
    holdout = [row for idx, row in enumerate(ordered) if idx % holdout_stride == 0]
    fit = [row for idx, row in enumerate(ordered) if idx % holdout_stride != 0]
    return fit, holdout


def split_rule_description(*, holdout_stride: int = 4, n_rows: int | None = None) -> dict:
    payload = {
        "rule": "sort by mrkPhotoId, holdout index % 4 == 0",
        "holdoutStride": holdout_stride,
        "reproducible": True,
        "notContiguousTail": True,
    }
    if n_rows is not None:
        holdout_count = sum(1 for idx in range(n_rows) if idx % holdout_stride == 0)
        payload["holdoutCount"] = holdout_count
        payload["fitCount"] = n_rows - holdout_count
    return payload
