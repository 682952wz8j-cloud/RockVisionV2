"""Deterministic spatially interleaved holdout. Never the last contiguous 12."""

from __future__ import annotations


def split_fit_holdout(rows: list[dict], holdout_stride: int = 4) -> tuple[list[dict], list[dict]]:
    """Every 4th correspondence by photoId is holdout (~12 of 47).

    Sorting is by MRK photoId (flight sequence). Taking indices 0,4,8,...
    interleaves holdout along the trajectory instead of taking one end.
    """
    ordered = sorted(rows, key=lambda item: (item["mrkPhotoId"], item["filename"]))
    holdout = [row for idx, row in enumerate(ordered) if idx % holdout_stride == 0]
    fit = [row for idx, row in enumerate(ordered) if idx % holdout_stride != 0]
    return fit, holdout


def split_rule_description() -> dict:
    return {
        "rule": "sort by mrkPhotoId, holdout index % 4 == 0",
        "holdoutStride": 4,
        "expectedHoldout": 12,
        "expectedFit": 35,
        "reproducible": True,
        "notContiguousTail": True,
    }
