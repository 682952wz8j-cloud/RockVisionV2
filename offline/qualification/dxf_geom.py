from __future__ import annotations

from pathlib import Path

MISSING = "missing"


def parse_dxf_polylines(text: str) -> dict:
    lines = text.splitlines()
    pairs: list[tuple[str, str]] = []
    i = 0
    while i + 1 < len(lines):
        code = lines[i].strip()
        value = lines[i + 1]
        pairs.append((code, value))
        i += 2

    header: dict[str, str] = {}
    entities: list[str] = []
    polylines: list[list[tuple[float, float, float]]] = []
    current: list[tuple[float, float, float]] | None = None
    in_entities = False
    pending_vertex: dict[str, float] = {}

    def flush_vertex() -> None:
        nonlocal pending_vertex, current
        if current is not None and "x" in pending_vertex:
            current.append(
                (
                    pending_vertex.get("x", 0.0),
                    pending_vertex.get("y", 0.0),
                    pending_vertex.get("z", 0.0),
                )
            )
        pending_vertex = {}

    idx = 0
    while idx < len(pairs):
        code, value = pairs[idx]
        val = value.strip()
        if code == "0" and val == "SECTION" and idx + 2 < len(pairs) and pairs[idx + 1][0] == "2":
            in_entities = pairs[idx + 1][1].strip() == "ENTITIES"
        if code == "9":
            key = val
            if idx + 1 < len(pairs):
                header[key] = pairs[idx + 1][1].strip()
        if code == "0":
            if val in {"POLYLINE", "LWPOLYLINE", "LINE", "VERTEX", "SEQEND", "ENDSEC"}:
                entities.append(val)
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
            number = float(val)
            pending_vertex[{ "10": "x", "20": "y", "30": "z"}[code]] = number
        idx += 1
    flush_vertex()
    if current:
        polylines.append(current)

    verts = [xyz for poly in polylines for xyz in poly]
    bbox = MISSING
    if verts:
        xs, ys, zs = zip(*verts)
        bbox = {
            "min": {"x": min(xs), "y": min(ys), "z": min(zs)},
            "max": {"x": max(xs), "y": max(ys), "z": max(zs)},
        }
    created_by = MISSING
    for pair in pairs[:20]:
        if "CloudCompare" in pair[1] or "Created by" in pair[1]:
            created_by = pair[1].strip()
            break
    return {
        "createdBy": created_by,
        "header": {k: header[k] for k in header if k in {"$ACADVER", "$INSUNITS", "$EXTMIN", "$EXTMAX"}},
        "insUnits": header.get("$INSUNITS", MISSING),
        "entityTypes": sorted(set(entities)),
        "polylineCount": len(polylines),
        "vertexCount": len(verts),
        "vertices": [{"x": x, "y": y, "z": z} for x, y, z in verts],
        "boundingBox": bbox,
        "zValuesPresent": any(abs(v[2]) > 0 for v in verts) if verts else False,
    }


def parse_dxf_file(path: Path) -> dict:
    return parse_dxf_polylines(path.read_text(encoding="utf-8", errors="replace"))
