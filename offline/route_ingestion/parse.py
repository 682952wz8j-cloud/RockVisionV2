"""Parse CloudCompare DXF polylines without modifying geometry."""

from __future__ import annotations

from pathlib import Path

from offline.qualification.dxf_geom import parse_dxf_file

from .schema import DUMMY_ORIGIN, MAX_ABS_METRES, MIN_POLYLINE_POINTS, REASON_GEOMETRY_INVALID, REASON_NOT_CLOUDCOMPARE, REASON_PARSE_FAILED


class RouteParseError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _pairs(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    pairs: list[tuple[str, str]] = []
    i = 0
    while i + 1 < len(lines):
        pairs.append((lines[i].strip(), lines[i + 1]))
        i += 2
    return pairs


def extract_polylines(text: str) -> list[list[tuple[float, float, float]]]:
    pairs = _pairs(text)
    polylines: list[list[tuple[float, float, float]]] = []
    current: list[tuple[float, float, float]] | None = None
    pending: dict[str, float] = {}

    def flush_vertex() -> None:
        nonlocal pending, current
        if current is not None and "x" in pending:
            current.append(
                (
                    pending.get("x", 0.0),
                    pending.get("y", 0.0),
                    pending.get("z", 0.0),
                )
            )
        pending = {}

    idx = 0
    while idx < len(pairs):
        code, value = pairs[idx]
        val = value.strip()
        if code == "0":
            if val == "POLYLINE":
                flush_vertex()
                if current:
                    polylines.append(current)
                current = []
            elif val == "VERTEX":
                flush_vertex()
            elif val == "SEQEND":
                flush_vertex()
                if current:
                    polylines.append(current)
                current = None
        if current is not None and code in {"10", "20", "30"}:
            pending[{"10": "x", "20": "y", "30": "z"}[code]] = float(val)
        idx += 1
    flush_vertex()
    if current:
        polylines.append(current)
    return polylines


def exclude_dummy_origin(vertices: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    kept: list[tuple[float, float, float]] = []
    for vertex in vertices:
        if vertex == DUMMY_ORIGIN:
            continue
        kept.append(vertex)
    return kept


def _finite(vertex: tuple[float, float, float]) -> bool:
    return all(value == value and abs(value) != float("inf") for value in vertex)


def ingest_polyline_from_dxf(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        facts = parse_dxf_file(path)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RouteParseError(REASON_PARSE_FAILED, f"{path.name}: {exc}") from exc
    created = str(facts.get("createdBy") or "")
    if "CloudCompare" not in created:
        raise RouteParseError(REASON_NOT_CLOUDCOMPARE, f"{path.name}: not a CloudCompare DXF")
    try:
        polylines = extract_polylines(text)
    except ValueError as exc:
        raise RouteParseError(REASON_PARSE_FAILED, f"{path.name}: {exc}") from exc
    nonempty = [poly for poly in polylines if poly]
    if len(nonempty) != 1:
        raise RouteParseError(
            REASON_GEOMETRY_INVALID,
            f"{path.name}: expected exactly one polyline, found {len(nonempty)}",
        )
    source_vertices = nonempty[0]
    ingested = exclude_dummy_origin(source_vertices)
    dummy_excluded = len(ingested) != len(source_vertices)
    if len(ingested) < MIN_POLYLINE_POINTS:
        raise RouteParseError(
            REASON_GEOMETRY_INVALID,
            f"{path.name}: ingested vertex count {len(ingested)} < {MIN_POLYLINE_POINTS}",
        )
    if any(not _finite(vertex) for vertex in ingested):
        raise RouteParseError(REASON_GEOMETRY_INVALID, f"{path.name}: non-finite vertex")
    if any(max(abs(c) for c in vertex) > MAX_ABS_METRES for vertex in ingested):
        raise RouteParseError(
            REASON_GEOMETRY_INVALID,
            f"{path.name}: vertex magnitude exceeds WallLocal envelope",
        )
    xs, ys, zs = zip(*ingested)
    return {
        "sourceFilename": path.name,
        "createdBy": created,
        "insUnits": facts.get("insUnits"),
        "sourceVertexCount": len(source_vertices),
        "dummyOriginExcluded": dummy_excluded,
        "ingestedVertices": [[x, y, z] for x, y, z in ingested],
        "pointCount": len(ingested),
        "bbox": {
            "xmin": min(xs),
            "xmax": max(xs),
            "ymin": min(ys),
            "ymax": max(ys),
            "zmin": min(zs),
            "zmax": max(zs),
        },
    }
