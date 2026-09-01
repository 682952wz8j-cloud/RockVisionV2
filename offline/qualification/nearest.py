from __future__ import annotations

import math
from collections import defaultdict

_MAX_NEAREST_CLOUD = 200_000
_MAX_NEAREST_QUERIES = 50_000


def nearest_distance_stats(
    queries: list[tuple[float, float, float]],
    cloud: list[tuple[float, float, float]],
    cell: float = 2.0,
) -> dict:
    if not queries or not cloud:
        return {"status": "missing", "reason": "no query or cloud points"}
    if len(cloud) > _MAX_NEAREST_CLOUD or len(queries) > _MAX_NEAREST_QUERIES:
        return {"status": "missing", "reason": "oversized point set; nearest search skipped"}
    grid: dict[tuple[int, int, int], list[tuple[float, float, float]]] = defaultdict(list)
    for x, y, z in cloud:
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            continue
        grid[(math.floor(x / cell), math.floor(y / cell), math.floor(z / cell))].append((x, y, z))
    distances: list[float] = []
    for qx, qy, qz in queries:
        if not (math.isfinite(qx) and math.isfinite(qy) and math.isfinite(qz)):
            continue
        gx, gy, gz = math.floor(qx / cell), math.floor(qy / cell), math.floor(qz / cell)
        best = float("inf")
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for x, y, z in grid.get((gx + dx, gy + dy, gz + dz), ()):
                        dist = math.sqrt((x - qx) ** 2 + (y - qy) ** 2 + (z - qz) ** 2)
                        if dist < best:
                            best = dist
        if best == float("inf"):
            for x, y, z in cloud:
                if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                    continue
                dist = math.sqrt((x - qx) ** 2 + (y - qy) ** 2 + (z - qz) ** 2)
                if dist < best:
                    best = dist
        if math.isfinite(best):
            distances.append(best)
    if not distances:
        return {"status": "missing", "reason": "no finite query or cloud points"}
    ordered = sorted(distances)
    def pct(p: float) -> float:
        if not ordered:
            return float("nan")
        idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
        return ordered[idx]
    mid = ordered[len(ordered) // 2]
    return {
        "status": "ok",
        "count": len(ordered),
        "min": ordered[0],
        "median": mid,
        "p90": pct(90),
        "max": ordered[-1],
        "cellMetersIfMetric": cell,
    }
