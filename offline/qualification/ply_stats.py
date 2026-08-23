from __future__ import annotations

import struct
from pathlib import Path

from .status import ProvenanceStatus, claim

MISSING = "missing"


def read_ply_header(path: Path) -> dict:
    comments: list[str] = []
    fmt = "ascii"
    vertex_count = 0
    face_count = 0
    vertex_props: list[str] = []
    section = None
    header_bytes = 0
    with path.open("rb") as handle:
        while True:
            raw = handle.readline()
            if not raw:
                break
            header_bytes += len(raw)
            line = raw.decode("ascii", errors="replace").strip()
            if line.startswith("format"):
                fmt = line.split()[1]
            elif line.startswith("comment"):
                comments.append(line[8:].strip())
            elif line.startswith("element vertex"):
                section = "vertex"
                vertex_count = int(line.split()[-1])
            elif line.startswith("element face"):
                section = "face"
                face_count = int(line.split()[-1])
            elif line.startswith("property") and section == "vertex":
                vertex_props.append(line)
            elif line == "end_header":
                break
    return {
        "format": fmt,
        "vertexCount": vertex_count,
        "faceCount": face_count,
        "vertexProperties": vertex_props,
        "comments": comments,
        "headerBytes": header_bytes,
        "unitsInHeader": MISSING,
        "crsInHeader": MISSING,
    }


def ply_vertex_bounds(path: Path, header: dict) -> dict:
    if header["format"] != "binary_little_endian":
        return {"status": "unsupported", "reason": f"PLY format {header['format']} not scanned"}
    props = header["vertexProperties"]
    if [p.split()[-1] for p in props[:3]] != ["x", "y", "z"]:
        return {"status": "unsupported", "reason": "first vertex properties are not x y z"}
    count = int(header["vertexCount"])
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    with path.open("rb") as handle:
        handle.seek(header["headerBytes"])
        chunk = handle.read(count * 12)
    if len(chunk) < count * 12:
        return {"status": "unreadable", "reason": "vertex payload shorter than header count"}
    for i in range(count):
        x, y, z = struct.unpack_from("<fff", chunk, i * 12)
        mins[0] = min(mins[0], x)
        mins[1] = min(mins[1], y)
        mins[2] = min(mins[2], z)
        maxs[0] = max(maxs[0], x)
        maxs[1] = max(maxs[1], y)
        maxs[2] = max(maxs[2], z)
    return {
        "status": "ok",
        "min": {"x": mins[0], "y": mins[1], "z": mins[2]},
        "max": {"x": maxs[0], "y": maxs[1], "z": maxs[2]},
        "extent": {
            "x": maxs[0] - mins[0],
            "y": maxs[1] - mins[1],
            "z": maxs[2] - mins[2],
        },
    }


def read_ply_xyz(path: Path, header: dict) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    if header["format"] != "binary_little_endian":
        return points
    count = int(header["vertexCount"])
    with path.open("rb") as handle:
        handle.seek(header["headerBytes"])
        chunk = handle.read(count * 12)
    for i in range(min(count, len(chunk) // 12)):
        points.append(struct.unpack_from("<fff", chunk, i * 12))
    return points


def qualify_ply_metric(header: dict, bounds: dict, metadata_xml: dict | None) -> list[dict]:
    claims = []
    if header.get("unitsInHeader") == MISSING:
        claims.append(
            claim(
                ProvenanceStatus.UNKNOWN,
                "PLY header does not declare units",
                ["No unit comment or property in the PLY header."],
            )
        )
    if metadata_xml and metadata_xml.get("srs") == "EPSG:32650":
        claims.append(
            claim(
                ProvenanceStatus.PROVEN,
                "Accompanying ModelMetadata declares SRS EPSG:32650",
                [
                    f"metadata.xml SRS={metadata_xml.get('srs')}",
                    f"SRSOrigin={metadata_xml.get('srsOrigin')}",
                ],
            )
        )
        claims.append(
            claim(
                ProvenanceStatus.SUPPORTED,
                "EPSG:32650 uses metres; PLY vertices appear local to SRSOrigin",
                [
                    "PRJ UNIT[metre] applies to EPSG:32650, not to the PLY file by itself.",
                    "Vertex magnitudes must be checked against a local origin, not assumed.",
                ],
            )
        )
    if bounds.get("status") == "ok":
        mx = max(abs(bounds["min"]["x"]), abs(bounds["max"]["x"]))
        if mx < 10000:
            claims.append(
                claim(
                    ProvenanceStatus.SUPPORTED,
                    "PLY vertex magnitudes are local, not raw UTM easting (~600000)",
                    [
                        f"X range {bounds['min']['x']:.3f} .. {bounds['max']['x']:.3f}",
                        "This is consistent with a translated local frame, not proof of metres by size alone.",
                    ],
                )
            )
        elif mx > 100000:
            claims.append(
                claim(
                    ProvenanceStatus.SUPPORTED,
                    "PLY vertex magnitudes look like projected global coordinates",
                    [f"X range {bounds['min']['x']:.3f} .. {bounds['max']['x']:.3f}"],
                )
            )
    return claims
