from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

KEYWORDS = (
    "origin",
    "crs",
    "epsg",
    "projection",
    "coordinate",
    "transform",
    "matrix",
    "offset",
    "scale",
    "gps",
    "rtk",
    "camera",
    "reconstruction",
    "aerotriangulation",
    "block",
    "srs",
    "enu",
    "utm",
)

_TEXT_EXT = {".json", ".xml", ".txt", ".md", ".csv", ".yml", ".yaml"}


def parse_model_metadata_xml(path: Path) -> dict | None:
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return None
    root = tree.getroot()
    srs = root.findtext("SRS")
    origin = root.findtext("SRSOrigin")
    if srs is None and origin is None:
        return None
    origin_xyz = None
    if origin:
        parts = [p.strip() for p in origin.split(",")]
        if len(parts) == 3:
            try:
                origin_xyz = [float(parts[0]), float(parts[1]), float(parts[2])]
            except ValueError:
                origin_xyz = None
    return {"srs": srs, "srsOriginText": origin, "srsOrigin": origin_xyz, "relativeHint": path.name}


def scan_text_file(path: Path, limit: int = 200_000) -> dict:
    text = path.read_bytes()[:limit].decode("utf-8", errors="replace")
    hits = sorted({kw for kw in KEYWORDS if re.search(rf"\b{re.escape(kw)}\b", text, re.I)})
    parsed_json = None
    if path.suffix.lower() == ".json":
        try:
            parsed_json = json.loads(text)
        except json.JSONDecodeError:
            parsed_json = None
    xml_meta = None
    if path.suffix.lower() == ".xml":
        xml_meta = parse_model_metadata_xml(path)
    return {"keywordHits": hits, "json": parsed_json, "modelMetadata": xml_meta}


def scan_records(incoming: Path, records: list[dict]) -> dict:
    interesting = []
    model_meta = None
    sfm_geo = None
    model_report = None
    map_report = None
    for rec in records:
        ext = rec.get("extension", "").lower()
        if rec["detectedType"] not in {"unknown", "structuredData", "metadata"} and ext != ".xml":
            if rec["filename"].lower() not in {"metadata.xml", "sfm_geo_desc.json", "model_report.json", "map_report.json"}:
                continue
        if ext not in _TEXT_EXT:
            continue
        path = incoming / rec["relativePath"]
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        scanned = scan_text_file(path)
        item = {
            "relativePath": rec["relativePath"],
            "detectedType": rec["detectedType"],
            "keywordHits": scanned["keywordHits"],
        }
        if scanned["modelMetadata"]:
            model_meta = {**scanned["modelMetadata"], "relativePath": rec["relativePath"]}
            item["reclassify"] = {
                "to": "geospatialMetadata",
                "reason": "ModelMetadata SRS/SRSOrigin present",
            }
        if rec["filename"] == "sfm_geo_desc.json" and isinstance(scanned["json"], dict):
            sfm_geo = scanned["json"]
        if rec["filename"] == "model_report.json" and isinstance(scanned["json"], dict):
            model_report = scanned["json"]
        if rec["filename"] == "map_report.json" and isinstance(scanned["json"], dict):
            map_report = scanned["json"]
        if scanned["keywordHits"] or item.get("reclassify"):
            interesting.append(item)
    return {
        "keywordFiles": interesting,
        "modelMetadata": model_meta,
        "sfmGeoDesc": sfm_geo,
        "modelReport": model_report,
        "mapReport": map_report,
    }
