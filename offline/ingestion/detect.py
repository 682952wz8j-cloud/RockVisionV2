from __future__ import annotations

import json
import re
from pathlib import Path

from .types import RawAssetType

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".heif",
    ".dng",
    ".tif",
    ".tiff",
    ".webp",
    ".raw",
    ".cr2",
    ".nef",
    ".arw",
    ".raf",
    ".orf",
}
RTK_EXTENSIONS = {
    ".mrk",
    ".obs",
    ".nav",
    ".rnx",
    ".rinex",
    ".rtcm",
    ".rtk",
    ".nmea",
    ".pos",
    ".pbk",
}
MODEL_EXTENSIONS = {
    ".obj",
    ".ply",
    ".fbx",
    ".usdz",
    ".glb",
    ".gltf",
    ".b3dm",
    ".osgb",
    ".stl",
}
STRUCTURED_EXTENSIONS = {".json", ".yaml", ".yml", ".xml", ".csv"}
METADATA_EXTENSIONS = {".txt", ".md"}
ROUTE_STRONG_EXTENSIONS = {".dxf", ".poly"}
GEOSPATIAL_SIDECAR_EXTENSIONS = {".tfw", ".prj"}

_SKIP_NAMES = {".ds_store"}


def read_head(path: Path, n: int = 4096) -> bytes:
    with path.open("rb") as handle:
        return handle.read(n)


def file_signature_label(head: bytes) -> str:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in {b"heic", b"heif", b"mif1", b"msf1"}:
        return "image/heic"
    if head.startswith(b"RIFF") and b"WEBP" in head[:16]:
        return "image/webp"
    if head.startswith(b"ply"):
        return "model/ply"
    if head.startswith(b"glTF"):
        return "model/gltf-binary"
    if head.startswith(b"b3dm"):
        return "model/vnd.cesium.b3dm"
    if head.startswith(b"PK"):
        return "application/zip"
    if head.lstrip().startswith((b"{", b"[")):
        return "application/json"
    if head.lstrip().startswith((b"<?xml", b"<")):
        return "application/xml"
    return "application/octet-stream"


def _looks_like_rinex(head: bytes) -> bool:
    text = _safe_text(head)
    return "RINEX" in text.upper() or bool(re.search(r"RINEX VERSION", text, re.I))


def _looks_like_dji_mrk(head: bytes) -> bool:
    text = _safe_text(head)
    return ",Lat" in text and ",Lon" in text and (",Ellh" in text or ",Alt" in text)


def _looks_like_dxf(head: bytes) -> bool:
    text = _safe_text(head)
    return "SECTION" in text and ("HEADER" in text or "ENTITIES" in text or "POLYLINE" in text)


def _looks_like_poly_xyz(head: bytes) -> bool:
    text = _safe_text(head)
    numeric_lines = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 3:
            return False
        try:
            float(parts[0])
            float(parts[1])
            float(parts[2])
        except ValueError:
            return False
        numeric_lines += 1
        if numeric_lines >= 2:
            return True
    return False


def _json_has_route_geometry(head: bytes) -> bool:
    text = _safe_text(head).lstrip()
    if not text.startswith(("{", "[")):
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return _payload_has_polyline(payload)


def _payload_has_polyline(payload: object) -> bool:
    if isinstance(payload, dict):
        if "polyline" in payload and isinstance(payload["polyline"], list) and payload["polyline"]:
            first = payload["polyline"][0]
            if isinstance(first, dict) and {"x", "y", "z"} <= set(first):
                return True
        for value in payload.values():
            if _payload_has_polyline(value):
                return True
    if isinstance(payload, list):
        for item in payload:
            if _payload_has_polyline(item):
                return True
    return False


def _safe_text(head: bytes) -> str:
    return head.decode("utf-8", errors="replace")


def classify_file(path: Path, max_head: int = 65536) -> tuple[RawAssetType, str, str]:
    return classify(path, read_head(path, max_head))


def classify(path: Path, head: bytes) -> tuple[RawAssetType, str, str]:
    """Return (type, detection_method, signature_label). Never uses parent folder names."""
    name = path.name.lower()
    ext = path.suffix.lower()
    signature = file_signature_label(head)

    if name in _SKIP_NAMES or name.startswith("._"):
        return RawAssetType.UNKNOWN, "macos_sidecar", signature

    if signature == "image/jpeg":
        return RawAssetType.IMAGE, "file_signature:jpeg", signature
    if signature == "image/png":
        return RawAssetType.IMAGE, "file_signature:png", signature
    if signature == "image/tiff":
        if ext == ".dng":
            return RawAssetType.IMAGE, "file_signature:tiff+extension:dng", "image/dng"
        return RawAssetType.IMAGE, "file_signature:tiff", signature
    if signature == "image/heic":
        return RawAssetType.IMAGE, "file_signature:heic", signature
    if signature == "image/webp":
        return RawAssetType.IMAGE, "file_signature:webp", signature

    if signature == "model/ply":
        return RawAssetType.MODEL_3D, "file_signature:ply", signature
    if signature == "model/gltf-binary":
        return RawAssetType.MODEL_3D, "file_signature:glb", signature
    if signature == "model/vnd.cesium.b3dm":
        return RawAssetType.MODEL_3D, "file_signature:b3dm", signature

    if _looks_like_rinex(head):
        return RawAssetType.RTK_GNSS, "content:rinex_header", signature
    if ext == ".mrk" or _looks_like_dji_mrk(head):
        return RawAssetType.RTK_GNSS, "content:dji_mrk" if _looks_like_dji_mrk(head) else "extension:mrk", signature
    if ext in RTK_EXTENSIONS:
        return RawAssetType.RTK_GNSS, f"extension:{ext.lstrip('.')}", signature

    if ext in ROUTE_STRONG_EXTENSIONS:
        if ext == ".dxf" and _looks_like_dxf(head):
            return RawAssetType.ROUTE_GEOMETRY, "extension:dxf+content:dxf", signature
        if ext == ".dxf":
            return RawAssetType.ROUTE_GEOMETRY, "extension:dxf", signature
        if ext == ".poly" and _looks_like_poly_xyz(head):
            return RawAssetType.ROUTE_GEOMETRY, "extension:poly+content:xyz", signature
        if ext == ".poly":
            return RawAssetType.ROUTE_GEOMETRY, "extension:poly", signature

    if ext == ".json" or signature == "application/json":
        if _json_has_route_geometry(head):
            return RawAssetType.ROUTE_GEOMETRY, "content:json_polyline", "application/json"
        return RawAssetType.STRUCTURED_DATA, "content:json_not_route", "application/json"

    if ext in GEOSPATIAL_SIDECAR_EXTENSIONS:
        return RawAssetType.GEOSPATIAL_SIDECAR, f"extension:{ext.lstrip('.')}", signature

    if ext == ".csv":
        return RawAssetType.STRUCTURED_DATA, "extension:csv_not_confirmed_route", signature
    if ext in STRUCTURED_EXTENSIONS:
        return RawAssetType.STRUCTURED_DATA, f"extension:{ext.lstrip('.')}", signature

    if ext == ".txt" and _looks_like_poly_xyz(head):
        return RawAssetType.ROUTE_GEOMETRY, "content:xyz_text", signature
    if ext in METADATA_EXTENSIONS:
        return RawAssetType.METADATA, f"extension:{ext.lstrip('.')}", signature

    if ext in IMAGE_EXTENSIONS:
        return RawAssetType.IMAGE, f"extension:{ext.lstrip('.')}", signature
    if ext in MODEL_EXTENSIONS:
        return RawAssetType.MODEL_3D, f"extension:{ext.lstrip('.')}", signature
    if signature == "application/zip" and ext == ".usdz":
        return RawAssetType.MODEL_3D, "file_signature:zip+extension:usdz", signature

    return RawAssetType.UNKNOWN, "unclassified", signature
