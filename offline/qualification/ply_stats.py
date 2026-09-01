from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from .status import ProvenanceStatus, claim

MISSING = "missing"

_SCALAR_TYPES: dict[str, tuple[str, int]] = {
    "char": ("b", 1),
    "int8": ("b", 1),
    "uchar": ("B", 1),
    "uint8": ("B", 1),
    "short": ("h", 2),
    "int16": ("h", 2),
    "ushort": ("H", 2),
    "uint16": ("H", 2),
    "int": ("i", 4),
    "int32": ("i", 4),
    "uint": ("I", 4),
    "uint32": ("I", 4),
    "float": ("f", 4),
    "float32": ("f", 4),
    "double": ("d", 8),
    "float64": ("d", 8),
}


class PlyDecodeError(ValueError):
    """Vertex layout cannot be decoded from the declared PLY properties."""


@dataclass(frozen=True)
class PlyVertexLayout:
    ply_format: str
    vertex_count: int
    header_bytes: int
    stride: int
    x_offset: int
    y_offset: int
    z_offset: int
    x_struct: str
    y_struct: str
    z_struct: str


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


def ply_vertex_layout(header: dict) -> PlyVertexLayout | None:
    """Return the packed binary_little_endian vertex layout, or None if not that format.

    Raises PlyDecodeError when the format is binary_little_endian but x/y/z cannot
    be resolved from the declared scalar properties.
    """
    if header.get("format") != "binary_little_endian":
        return None
    offset = 0
    fields: dict[str, tuple[int, str]] = {}
    for raw in header.get("vertexProperties") or []:
        parts = raw.split()
        if len(parts) >= 5 and parts[1] == "list":
            name = parts[-1]
            if name in {"x", "y", "z"}:
                raise PlyDecodeError(f"PLY vertex property {name} is a list, not a scalar")
            raise PlyDecodeError("PLY vertex element contains a list property; packed stride is undefined")
        if len(parts) < 3:
            raise PlyDecodeError(f"unrecognized PLY vertex property: {raw}")
        type_name = parts[1]
        name = parts[-1]
        mapped = _SCALAR_TYPES.get(type_name)
        if mapped is None:
            raise PlyDecodeError(f"unsupported PLY vertex property type {type_name!r} for {name}")
        code, size = mapped
        if name in {"x", "y", "z"}:
            fields[name] = (offset, "<" + code)
        offset += size
    for axis in ("x", "y", "z"):
        if axis not in fields:
            raise PlyDecodeError(f"PLY vertex properties do not declare scalar {axis}")
    if offset <= 0:
        raise PlyDecodeError("PLY vertex record stride is zero")
    return PlyVertexLayout(
        ply_format="binary_little_endian",
        vertex_count=int(header["vertexCount"]),
        header_bytes=int(header["headerBytes"]),
        stride=offset,
        x_offset=fields["x"][0],
        y_offset=fields["y"][0],
        z_offset=fields["z"][0],
        x_struct=fields["x"][1],
        y_struct=fields["y"][1],
        z_struct=fields["z"][1],
    )


def _xyz_at(payload: bytes, index: int, layout: PlyVertexLayout) -> tuple[float, float, float]:
    base = index * layout.stride
    x = struct.unpack_from(layout.x_struct, payload, base + layout.x_offset)[0]
    y = struct.unpack_from(layout.y_struct, payload, base + layout.y_offset)[0]
    z = struct.unpack_from(layout.z_struct, payload, base + layout.z_offset)[0]
    return (float(x), float(y), float(z))


def _read_vertex_payload(path: Path, layout: PlyVertexLayout) -> bytes:
    expected = layout.vertex_count * layout.stride
    with path.open("rb") as handle:
        handle.seek(layout.header_bytes)
        payload = handle.read(expected)
    if len(payload) < expected:
        raise PlyDecodeError(
            f"PLY vertex payload shorter than header count: got {len(payload)} bytes, "
            f"need {expected} ({layout.vertex_count} * stride {layout.stride})"
        )
    return payload


def ply_vertex_bounds(path: Path, header: dict) -> dict:
    if header["format"] != "binary_little_endian":
        return {"status": "unsupported", "reason": f"PLY format {header['format']} not scanned"}
    layout = ply_vertex_layout(header)
    assert layout is not None
    payload = _read_vertex_payload(path, layout)
    if layout.vertex_count == 0:
        return {"status": "ok", "min": {"x": 0.0, "y": 0.0, "z": 0.0}, "max": {"x": 0.0, "y": 0.0, "z": 0.0}, "extent": {"x": 0.0, "y": 0.0, "z": 0.0}}
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    for i in range(layout.vertex_count):
        x, y, z = _xyz_at(payload, i, layout)
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
    if header["format"] != "binary_little_endian":
        return []
    layout = ply_vertex_layout(header)
    assert layout is not None
    payload = _read_vertex_payload(path, layout)
    return [_xyz_at(payload, i, layout) for i in range(layout.vertex_count)]


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
