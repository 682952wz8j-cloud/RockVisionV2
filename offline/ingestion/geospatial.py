from __future__ import annotations

import re
from pathlib import Path

from .types import MISSING, InventoryRecord, RawAssetType

RASTER_EXTENSIONS = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".img"}
_EPSG_AUTHORITY = re.compile(r'AUTHORITY\s*\[\s*"EPSG"\s*,\s*"(\d+)"\s*\]', re.I)
_CRS_NAME = re.compile(r'^(PROJCS|GEOGCS|GEOCCS|COMPD_CS|VERT_CS)\s*\[\s*"([^"]+)"', re.I | re.S)


def read_text_limited(path: Path, limit: int = 1_000_000) -> str:
    with path.open("rb") as handle:
        return handle.read(limit).decode("utf-8", errors="replace")


def parse_tfw(text: str) -> dict:
    numbers: list[float] = []
    leftover: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            numbers.append(float(line))
        except ValueError:
            leftover.append(line)
    if len(numbers) < 6:
        return {
            "kind": "tfw",
            "parsed": False,
            "parseStatus": "world file does not contain six numeric parameters",
            "parameters": MISSING,
        }
    params = {
        "pixelSizeX": numbers[0],
        "rotationY": numbers[1],
        "rotationX": numbers[2],
        "pixelSizeY": numbers[3],
        "upperLeftX": numbers[4],
        "upperLeftY": numbers[5],
    }
    extra = numbers[6:]
    result = {
        "kind": "tfw",
        "parsed": True,
        "parseStatus": "ok",
        "parameters": params,
    }
    if extra or leftover:
        result["unparsedTrailing"] = extra + leftover
    return result


def parse_prj(text: str) -> dict:
    wkt = text.strip()
    if not wkt:
        return {
            "kind": "prj",
            "parsed": False,
            "parseStatus": "empty PRJ",
            "wkt": MISSING,
            "crsName": MISSING,
            "epsg": MISSING,
        }
    name_match = _CRS_NAME.search(wkt)
    epsg_hits = _EPSG_AUTHORITY.findall(wkt)
    return {
        "kind": "prj",
        "parsed": True,
        "parseStatus": "ok",
        "wkt": wkt,
        "crsName": name_match.group(2) if name_match else MISSING,
        "epsg": f"EPSG:{epsg_hits[-1]}" if epsg_hits else MISSING,
    }


def inspect_sidecar(path: Path) -> dict:
    ext = path.suffix.lower()
    text = read_text_limited(path)
    if ext == ".tfw":
        return parse_tfw(text)
    if ext == ".prj":
        return parse_prj(text)
    return {"kind": ext.lstrip("."), "parsed": False, "parseStatus": "unsupported sidecar"}


def associate_sidecars(records: list[InventoryRecord]) -> None:
    rasters_by_dir: dict[str, list[InventoryRecord]] = {}
    for rec in records:
        if rec.detected_type != RawAssetType.IMAGE:
            continue
        if rec.extension not in RASTER_EXTENSIONS:
            continue
        parent = str(Path(rec.relative_path).parent)
        rasters_by_dir.setdefault(parent, []).append(rec)

    for rec in records:
        if rec.detected_type != RawAssetType.GEOSPATIAL_SIDECAR:
            continue
        parent = str(Path(rec.relative_path).parent)
        stem = Path(rec.filename).stem.lower()
        associated = [
            raster.relative_path
            for raster in rasters_by_dir.get(parent, [])
            if Path(raster.filename).stem.lower() == stem
        ]
        sidecar = rec.extra.setdefault("geospatialSidecar", {})
        sidecar["associatedRasters"] = associated
        if not associated:
            sidecar["associatedRasters"] = []
            sidecar["association"] = "no same-stem raster in the same directory"
        else:
            sidecar["association"] = "same-stem raster in the same directory"
