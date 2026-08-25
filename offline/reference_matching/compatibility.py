"""Same-image and leave-one-out compatibility on a frozen artifact."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np

from .constants import CANDIDATE_K, MIN_DISTINCT_POINT3D_FOR_RATIO, RATIO_THRESHOLD
from .extract import ExtractedImage
from .match import MatchResult, knn_l2, match_queries, provenance_for
from .serialize import load_frozen


def _quantiles(values: list[float]) -> dict:
    if not values:
        return {"min": None, "p10": None, "median": None, "p90": None, "max": None, "count": 0}
    arr = np.asarray(values, dtype=np.float64)
    return {
        "min": float(np.min(arr)),
        "p10": float(np.quantile(arr, 0.10)),
        "median": float(np.median(arr)),
        "p90": float(np.quantile(arr, 0.90)),
        "max": float(np.max(arr)),
        "count": int(len(arr)),
    }


def _winning_image_ids(result: MatchResult, rows: list[dict]) -> list[int]:
    out: list[int] = []
    for record in result.accepted_after_ratio:
        if record.reference_row is None:
            continue
        out.append(int(rows[record.reference_row]["referenceImageID"]))
    return out


def summarize_compatibility(
    *,
    title: str,
    query_image_id: int,
    query_image_name: str,
    query_count: int,
    result: MatchResult,
    rows: list[dict],
    excluded_rows: int,
    selection_reason: str,
) -> dict:
    winners = _winning_image_ids(result, rows)
    counts = Counter(winners)
    self_hits = int(counts.get(query_image_id, 0))
    unique_ids = {record.point3d_id for record in result.accepted_unique_point3d}
    sample = []
    for record in result.accepted_unique_point3d[:20]:
        item = provenance_for(record, rows)
        if item:
            sample.append(item)
    distances = [r.distance for r in result.accepted_after_ratio if r.distance is not None]
    ratios = [r.ratio for r in result.accepted_after_ratio if r.ratio is not None]
    unique_nonzero = len(result.accepted_unique_point3d) > 0
    near_zero = query_count >= 1000 and len(result.accepted_unique_point3d) == 0
    return {
        "title": title,
        "queryImageId": query_image_id,
        "queryImageName": query_image_name,
        "selectionReason": selection_reason,
        "queryKp": query_count,
        "queryImageRowsExcluded": excluded_rows,
        "acceptedAfterRatio": len(result.accepted_after_ratio),
        "acceptedUniquePoint3D": len(result.accepted_unique_point3d),
        "insufficientDistinctPoint3D": result.insufficient_distinct_point3d,
        "ratioRejected": result.ratio_rejected,
        "duplicatePoint3DRejected": result.duplicate_point3d_rejected,
        "rawDescriptorCandidates": result.raw_descriptor_candidates,
        "uniquePoint3DCandidates": result.unique_point3d_candidates,
        "candidateKTruncatedQueries": result.candidate_k_truncated_queries,
        "distanceDistribution": _quantiles(distances),
        "ratioDistribution": _quantiles(ratios),
        "winningReferenceImageCounts": {str(k): v for k, v in counts.most_common(12)},
        "acceptedAfterRatioSelfImage": self_hits,
        "acceptedAfterRatioSelfImageFraction": (self_hits / len(winners)) if winners else 0.0,
        "uniquePoint3DIds": len(unique_ids),
        "nearZeroUniquePoint3D": near_zero,
        "hasNonZeroUniquePoint3D": unique_nonzero,
        "candidateK": CANDIDATE_K,
        "minDistinctPoint3DForRatio": MIN_DISTINCT_POINT3D_FOR_RATIO,
        "ratioThreshold": RATIO_THRESHOLD,
        "diagnosticMatches": sample,
        "humanReview": True,
    }


def _run(_cv2, query_desc: np.ndarray, reference_desc: np.ndarray, point3d_ids: np.ndarray) -> MatchResult:
    indices, distances = knn_l2(query_desc, reference_desc, k=CANDIDATE_K)
    return match_queries(
        query_desc,
        reference_desc,
        point3d_ids,
        knn_indices=indices,
        knn_distances=distances,
        candidate_k=CANDIDATE_K,
    )


def same_image_compatibility(
    cv2,
    frozen: dict,
    query: ExtractedImage,
    selection_reason: str,
) -> dict:
    result = _run(cv2, query.descriptors, frozen["descriptors"], frozen["point3dIds"])
    return summarize_compatibility(
        title="same-image",
        query_image_id=query.image_id,
        query_image_name=query.name,
        query_count=query.keypoint_count,
        result=result,
        rows=frozen["rows"],
        excluded_rows=0,
        selection_reason=selection_reason,
    )


def loo_compatibility(
    cv2,
    frozen: dict,
    query: ExtractedImage,
    selection_reason: str,
) -> dict:
    mask = frozen["imageIds"] != int(query.image_id)
    excluded = int(np.size(mask) - np.count_nonzero(mask))
    result = _run(cv2, query.descriptors, frozen["descriptors"][mask], frozen["point3dIds"][mask])
    # remap reference_row from masked array back to frozen row index for provenance
    kept_index = np.nonzero(mask)[0]
    remapped_rows = []
    for record in result.accepted_after_ratio + result.accepted_unique_point3d:
        remapped_rows.append(record)
    for record in result.records:
        if record.reference_row is not None and 0 <= record.reference_row < len(kept_index):
            record.reference_row = int(kept_index[record.reference_row])
    summary = summarize_compatibility(
        title="loo-cross-view",
        query_image_id=query.image_id,
        query_image_name=query.name,
        query_count=query.keypoint_count,
        result=result,
        rows=frozen["rows"],
        excluded_rows=excluded,
        selection_reason=selection_reason,
    )
    if excluded <= 0:
        summary["nearZeroUniquePoint3D"] = True
        summary["looExclusionFailed"] = True
    other_winners = 0
    for record in result.accepted_after_ratio:
        if record.reference_row is None:
            continue
        if int(frozen["rows"][record.reference_row]["referenceImageID"]) != int(query.image_id):
            other_winners += 1
    summary["winningImageNotQuery"] = other_winners
    summary["winningImageIsQuery"] = len(result.accepted_after_ratio) - other_winners
    return summary


def select_compatibility_images(rows: list[dict], extracted: list[ExtractedImage], loo_count: int = 2) -> dict:
    by_id = {item.image_id: item for item in extracted}
    per_image_p3d: dict[int, set[int]] = {}
    per_image_rows: dict[int, int] = {}
    for row in rows:
        iid = int(row["referenceImageID"])
        per_image_rows[iid] = per_image_rows.get(iid, 0) + 1
        per_image_p3d.setdefault(iid, set()).add(int(row["point3DID"]))
    all_except: dict[int, set[int]] = {}
    for iid, pids in per_image_p3d.items():
        others: set[int] = set()
        for other, opids in per_image_p3d.items():
            if other != iid:
                others |= opids
        all_except[iid] = pids & others
    ranked = sorted(
        per_image_p3d,
        key=lambda iid: (len(all_except[iid]), per_image_rows.get(iid, 0), -iid),
        reverse=True,
    )
    same_id = ranked[0] if ranked else None
    loo_ids = ranked[:loo_count]
    def reason(iid: int) -> str:
        return (
            f"registered image with {per_image_rows.get(iid, 0)} accepted descriptors, "
            f"{len(per_image_p3d.get(iid, set()))} unique Point3D, "
            f"{len(all_except.get(iid, set()))} of those Point3D also observed in other accepted images"
        )
    return {
        "sameImage": by_id.get(same_id) if same_id is not None else None,
        "sameImageReason": reason(same_id) if same_id is not None else "",
        "loo": [by_id[i] for i in loo_ids if i in by_id],
        "looReasons": {i: reason(i) for i in loo_ids},
        "rankedImageIds": ranked,
    }


def load_frozen_artifact(dest: Path) -> dict:
    return load_frozen(dest)
