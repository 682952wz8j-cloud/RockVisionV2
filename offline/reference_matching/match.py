"""Point3D-aware matcher: BF L2 KNN → group → distinct ratio → unique Point3D."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .constants import CANDIDATE_K, DESCRIPTOR_DIM, MIN_DISTINCT_POINT3D_FOR_RATIO, RATIO_THRESHOLD

REASON_ACCEPTED = "acceptedAfterRatio"
REASON_INSUFFICIENT = "insufficientDistinctPoint3D"
REASON_RATIO = "ratioRejected"
REASON_EMPTY = "empty"
REASON_NON_FINITE = "nonFiniteDescriptor"
REASON_BAD_DIM = "badDescriptorDimension"


@dataclass
class MatchRecord:
    query_index: int
    reason: str
    point3d_id: int | None = None
    distance: float | None = None
    second_distance: float | None = None
    ratio: float | None = None
    reference_row: int | None = None
    raw_descriptor_candidates: int = 0
    unique_point3d_candidates: int = 0
    candidate_k_truncated_distinct: bool = False


@dataclass
class MatchResult:
    records: list[MatchRecord]
    accepted_after_ratio: list[MatchRecord]
    accepted_unique_point3d: list[MatchRecord]
    insufficient_distinct_point3d: int
    ratio_rejected: int
    duplicate_point3d_rejected: int
    raw_descriptor_candidates: int
    unique_point3d_candidates: int
    candidate_k_truncated_queries: int
    empty_query: bool
    empty_reference: bool


def knn_l2(query: np.ndarray, reference: np.ndarray, k: int = CANDIDATE_K) -> tuple[np.ndarray, np.ndarray]:
    query = np.asarray(query, dtype=np.float32)
    reference = np.asarray(reference, dtype=np.float32)
    qn = 0 if query.size == 0 else int(query.shape[0])
    rn = 0 if reference.size == 0 else int(reference.shape[0])
    kk = max(0, min(int(k), rn))
    if qn == 0 or kk == 0:
        return (
            np.full((qn, max(int(k), 0)), -1, dtype=np.int64),
            np.full((qn, max(int(k), 0)), np.inf, dtype=np.float32),
        )
    ref2 = np.sum(reference * reference, axis=1)
    indices = np.full((qn, k), -1, dtype=np.int64)
    distances = np.full((qn, k), np.inf, dtype=np.float32)
    batch = 256 if qn >= 1000 else 64
    last_report = -1
    for start in range(0, qn, batch):
        qb = query[start : start + batch]
        q2 = np.sum(qb * qb, axis=1, keepdims=True)
        dots = qb @ reference.T
        d2 = np.maximum(q2 + ref2.reshape(1, -1) - 2.0 * dots, 0.0)
        dist = np.sqrt(d2, dtype=np.float32)
        part = np.argpartition(dist, kth=kk - 1, axis=1)[:, :kk]
        picked = np.take_along_axis(dist, part, axis=1)
        order = np.argsort(picked, axis=1)
        part = np.take_along_axis(part, order, axis=1)
        picked = np.take_along_axis(picked, order, axis=1)
        indices[start : start + len(qb), :kk] = part
        distances[start : start + len(qb), :kk] = picked
        done = start + len(qb)
        if qn >= 5000 and (done == qn or done // 20000 != last_report):
            last_report = done // 20000
            print(f"knn_l2 {done}/{qn} against {rn} reference rows", flush=True)
    return indices, distances


def opencv_bf_knn(cv2, query: np.ndarray, reference: np.ndarray, k: int = CANDIDATE_K) -> tuple[np.ndarray, np.ndarray]:
    qn = 0 if query is None or np.asarray(query).size == 0 else int(query.shape[0])
    rn = 0 if reference is None or np.asarray(reference).size == 0 else int(reference.shape[0])
    if qn == 0 or rn == 0 or k <= 0:
        return knn_l2(query if query is not None else np.zeros((0, DESCRIPTOR_DIM)), reference if reference is not None else np.zeros((0, DESCRIPTOR_DIM)), k)
    matcher = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
    pairs = matcher.knnMatch(np.asarray(query, dtype=np.float32), np.asarray(reference, dtype=np.float32), k=min(k, rn))
    indices = np.full((qn, k), -1, dtype=np.int64)
    distances = np.full((qn, k), np.inf, dtype=np.float32)
    for qi, matches in enumerate(pairs):
        for j, match in enumerate(matches[:k]):
            indices[qi, j] = int(match.trainIdx)
            distances[qi, j] = float(match.distance)
    return indices, distances


def _group_point3d(
    row_indices: np.ndarray,
    row_distances: np.ndarray,
    point3d_ids: np.ndarray,
) -> list[tuple[int, float, int]]:
    best: dict[int, tuple[float, int]] = {}
    for idx, dist in zip(row_indices.tolist(), row_distances.tolist()):
        if idx < 0 or not np.isfinite(dist):
            continue
        pid = int(point3d_ids[idx])
        prev = best.get(pid)
        if prev is None or dist < prev[0] or (dist == prev[0] and idx < prev[1]):
            best[pid] = (float(dist), int(idx))
    ranked = sorted(best.items(), key=lambda item: (item[1][0], item[0], item[1][1]))
    return [(pid, dist, row) for pid, (dist, row) in ranked]


def match_queries(
    query: np.ndarray,
    reference: np.ndarray,
    point3d_ids: np.ndarray,
    *,
    knn_indices: np.ndarray | None = None,
    knn_distances: np.ndarray | None = None,
    candidate_k: int = CANDIDATE_K,
    min_distinct: int = MIN_DISTINCT_POINT3D_FOR_RATIO,
    ratio_threshold: float = RATIO_THRESHOLD,
) -> MatchResult:
    query = np.asarray(query, dtype=np.float32) if query is not None else np.zeros((0, DESCRIPTOR_DIM), dtype=np.float32)
    reference = np.asarray(reference, dtype=np.float32) if reference is not None else np.zeros((0, DESCRIPTOR_DIM), dtype=np.float32)
    point3d_ids = np.asarray(point3d_ids, dtype=np.int64)
    empty_query = query.size == 0
    empty_reference = reference.size == 0
    if query.size and (query.ndim != 2 or query.shape[1] != DESCRIPTOR_DIM):
        raise ValueError(f"query dim {getattr(query, 'shape', None)} != (N,{DESCRIPTOR_DIM})")
    if reference.size and (reference.ndim != 2 or reference.shape[1] != DESCRIPTOR_DIM):
        raise ValueError(f"reference dim {getattr(reference, 'shape', None)} != (N,{DESCRIPTOR_DIM})")
    if not empty_reference and len(point3d_ids) != len(reference):
        raise ValueError("point3d_ids length != reference rows")

    if knn_indices is None or knn_distances is None:
        knn_indices, knn_distances = knn_l2(query, reference, k=candidate_k)

    records: list[MatchRecord] = []
    raw_total = 0
    unique_total = 0
    truncated = 0
    for qi in range(len(query)):
        row = query[qi]
        if not np.isfinite(row).all():
            records.append(MatchRecord(query_index=qi, reason=REASON_NON_FINITE))
            continue
        idxs = knn_indices[qi]
        dists = knn_distances[qi]
        valid = (idxs >= 0) & np.isfinite(dists)
        raw_count = int(np.sum(valid))
        raw_total += raw_count
        grouped = _group_point3d(idxs[valid], dists[valid], point3d_ids)
        unique_count = len(grouped)
        unique_total += unique_count
        truncated_flag = raw_count == candidate_k and unique_count < min_distinct
        if truncated_flag:
            truncated += 1
        if unique_count < min_distinct:
            records.append(
                MatchRecord(
                    query_index=qi,
                    reason=REASON_INSUFFICIENT,
                    raw_descriptor_candidates=raw_count,
                    unique_point3d_candidates=unique_count,
                    candidate_k_truncated_distinct=truncated_flag,
                    point3d_id=grouped[0][0] if grouped else None,
                    distance=grouped[0][1] if grouped else None,
                    reference_row=grouped[0][2] if grouped else None,
                )
            )
            continue
        best_pid, best_d, best_row = grouped[0]
        second_pid, second_d, _second_row = grouped[1]
        ratio = float(best_d / second_d) if second_d > 0 else float("inf")
        reason = REASON_ACCEPTED if ratio < ratio_threshold else REASON_RATIO
        records.append(
            MatchRecord(
                query_index=qi,
                reason=reason,
                point3d_id=best_pid,
                distance=float(best_d),
                second_distance=float(second_d),
                ratio=ratio,
                reference_row=best_row,
                raw_descriptor_candidates=raw_count,
                unique_point3d_candidates=unique_count,
                candidate_k_truncated_distinct=truncated_flag,
            )
        )

    accepted = [r for r in records if r.reason == REASON_ACCEPTED]
    unique_kept, dup_rejected = unique_point3d_dedup(accepted)
    return MatchResult(
        records=records,
        accepted_after_ratio=accepted,
        accepted_unique_point3d=unique_kept,
        insufficient_distinct_point3d=sum(1 for r in records if r.reason == REASON_INSUFFICIENT),
        ratio_rejected=sum(1 for r in records if r.reason == REASON_RATIO),
        duplicate_point3d_rejected=dup_rejected,
        raw_descriptor_candidates=raw_total,
        unique_point3d_candidates=unique_total,
        candidate_k_truncated_queries=truncated,
        empty_query=empty_query,
        empty_reference=empty_reference,
    )


def unique_point3d_dedup(accepted: list[MatchRecord]) -> tuple[list[MatchRecord], int]:
    best: dict[int, MatchRecord] = {}
    for record in accepted:
        if record.point3d_id is None:
            continue
        current = best.get(record.point3d_id)
        if current is None or _better_unique(record, current):
            best[record.point3d_id] = record
    kept = sorted(best.values(), key=lambda r: r.query_index)
    return kept, max(0, len(accepted) - len(kept))


def _better_unique(new: MatchRecord, old: MatchRecord) -> bool:
    new_ratio = float("inf") if new.ratio is None else new.ratio
    old_ratio = float("inf") if old.ratio is None else old.ratio
    if new_ratio != old_ratio:
        return new_ratio < old_ratio
    new_d = float("inf") if new.distance is None else new.distance
    old_d = float("inf") if old.distance is None else old.distance
    if new_d != old_d:
        return new_d < old_d
    return new.query_index < old.query_index


def provenance_for(
    record: MatchRecord,
    rows: list[dict],
) -> dict | None:
    if record.reference_row is None or record.reference_row < 0 or record.reference_row >= len(rows):
        return None
    row = rows[record.reference_row]
    return {
        "queryIndex": record.query_index,
        "point3DID": record.point3d_id,
        "distance": record.distance,
        "secondDistance": record.second_distance,
        "ratio": record.ratio,
        "referenceRow": record.reference_row,
        "referenceImageID": row.get("referenceImageID"),
        "referenceImageName": row.get("referenceImageName"),
        "referenceKeypointX": row.get("referenceKeypointX"),
        "referenceKeypointY": row.get("referenceKeypointY"),
    }
