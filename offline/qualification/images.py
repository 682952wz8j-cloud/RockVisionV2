from __future__ import annotations

import re
from pathlib import Path

from .status import ProvenanceStatus, claim

DJI_NAME = re.compile(r"^DJI_\d{14}_\d{4}_[A-Z]\.(JPE?G)$", re.I)
IPHONE_NAME = re.compile(r"^IMG_\d{4}\.(HEIC|HEIF|JPE?G)$", re.I)
XYZ_TILE = re.compile(r"(?:^|/)(\d{1,2})/(\d+)/(\d+)\.png$", re.I)
MISSING = "missing"


def classify_image(record: dict, ply_texture_names: set[str]) -> dict:
    rel = record["relativePath"]
    name = record["filename"]
    ext = record.get("extension", "").lower()
    image = record.get("image") or {}
    width = image.get("pixelWidth", MISSING)
    height = image.get("pixelHeight", MISSING)
    make = image.get("cameraMake", MISSING)
    model = image.get("cameraModel", MISSING)
    gps = image.get("gpsLatitude", MISSING)
    software = image.get("software", MISSING)
    path_l = rel.replace("\\", "/").lower()

    role = "unknownImage"
    status = ProvenanceStatus.UNKNOWN
    reasons: list[str] = []
    colmap = False

    if ext in {".tif", ".tiff"}:
        role = "orthophotoOrRaster"
        status = ProvenanceStatus.PROVEN
        reasons.append("GeoTIFF candidate with raster extension; sidecar association decided separately.")
    elif XYZ_TILE.search(rel.replace("\\", "/")) and width == 256 and height == 256:
        role = "derivedModelingImage"
        status = ProvenanceStatus.PROVEN
        reasons.append("256×256 PNG in {z}/{x}/{y} tile path; not a camera exposure.")
    elif name.lower() in {n.lower() for n in ply_texture_names} or "terra_ply/" in path_l:
        role = "textureAsset"
        status = ProvenanceStatus.PROVEN
        reasons.append("JPEG is a PLY TextureFile or sits beside the textured PLY.")
    elif any(token in path_l for token in ("/report/", "screennail", "overlap_render", "reprojection")):
        role = "derivedModelingImage"
        status = ProvenanceStatus.PROVEN
        reasons.append("Filename/path is a modeling or QA report image.")
    elif ext in {".jpg", ".jpeg"} and make != MISSING and DJI_NAME.match(name):
        role = "originalCameraImage"
        status = ProvenanceStatus.PROVEN
        colmap = True
        reasons.append("DJI filename + EXIF camera make/model.")
        if gps == MISSING:
            reasons.append("GPS EXIF is missing on this original camera file.")
    elif ext in {".heic", ".heif"} or (
        ext in {".jpg", ".jpeg"} and IPHONE_NAME.match(name)
    ):
        apple = "apple" in str(make).lower() or "iphone" in str(model).lower()
        named = bool(IPHONE_NAME.match(name))
        if apple or named or make != MISSING:
            role = "originalCameraImage"
            status = ProvenanceStatus.PROVEN if apple or make != MISSING else ProvenanceStatus.SUPPORTED
            colmap = False
            reasons.append("iPhone/HEIC original camera file; not auto-listed as COLMAP input.")
            if gps == MISSING:
                reasons.append("No GPS on this iPhone file; indoor/near-field visual pose does not require GPS.")
        else:
            role = "unknownImage"
            status = ProvenanceStatus.UNKNOWN
            reasons.append("HEIC/iPhone-like file without camera EXIF or IMG_ name.")
    elif ext in {".jpg", ".jpeg"} and make != MISSING:
        role = "originalCameraImage"
        status = ProvenanceStatus.SUPPORTED
        colmap = True
        reasons.append("EXIF camera make/model present; filename is not a standard DJI pattern.")
    elif ext in {".png", ".jpg", ".jpeg", ".heic", ".heif"}:
        role = "unknownImage"
        status = ProvenanceStatus.UNKNOWN
        reasons.append("No camera EXIF, tile pattern, texture link, or report marker.")

    return {
        "relativePath": rel,
        "filename": name,
        "role": role,
        "colmapSourceCandidate": colmap,
        "classification": claim(status, f"{name} classified as {role}", reasons),
        "dimensions": {"width": width, "height": height},
        "format": image.get("imageFormat", ext),
        "cameraMake": make,
        "cameraModel": model,
        "focalLength": image.get("focalLength", MISSING),
        "focalLength35mm": image.get("focalLength35mm", MISSING),
        "captureTimestamp": image.get("captureTimestamp", MISSING),
        "gpsLatitude": gps,
        "gpsLongitude": image.get("gpsLongitude", MISSING),
        "gpsAltitude": image.get("gpsAltitude", MISSING),
        "hasExif": image.get("hasExif", MISSING),
        "software": software,
        "orientation": image.get("orientation", MISSING),
        "lensModel": image.get("lensModel", MISSING),
        "parentDirectory": str(Path(rel).parent),
        "captureSession": MISSING,
        "sourceDevice": MISSING,
        "captureDate": MISSING,
        "qualificationStatus": status.value,
    }


def collect_ply_texture_names(incoming: Path, ply_rel: str | None) -> set[str]:
    names: set[str] = set()
    if not ply_rel:
        return names
    path = incoming / ply_rel
    if not path.is_file():
        return names
    with path.open("rb") as handle:
        while True:
            line = handle.readline()
            if not line or line.strip() == b"end_header":
                break
            text = line.decode("ascii", errors="replace")
            if text.lower().startswith("comment texturefile"):
                names.add(text.split(None, 2)[-1].strip())
    return names
