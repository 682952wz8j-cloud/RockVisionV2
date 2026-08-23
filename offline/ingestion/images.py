from __future__ import annotations

from pathlib import Path
from typing import Any

from .types import MISSING, ImageInfo, ValidationStatus


def image_to_json(info: ImageInfo) -> dict[str, object]:
    return {
        "pixelWidth": info.pixel_width,
        "pixelHeight": info.pixel_height,
        "hasExif": info.has_exif,
        "cameraMake": info.camera_make,
        "cameraModel": info.camera_model,
        "focalLength": info.focal_length,
        "focalLength35mm": info.focal_length_35mm,
        "captureTimestamp": info.capture_timestamp,
        "gpsLatitude": info.gps_latitude,
        "gpsLongitude": info.gps_longitude,
        "gpsAltitude": info.gps_altitude,
        "orientation": info.orientation,
        "imageFormat": info.image_format,
        "lensModel": info.lens_model,
    }

try:
    from PIL import ExifTags, Image
except ImportError:  # pragma: no cover
    ExifTags = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]


def _ratio(value: Any) -> str:
    if value is None:
        return MISSING
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        den = float(value.denominator)
        if den == 0:
            return MISSING
        return str(float(value.numerator) / den)
    if isinstance(value, tuple) and len(value) == 2 and value[1]:
        return str(float(value[0]) / float(value[1]))
    return str(value)


def _gps_to_degrees(coord: Any, ref: Any) -> str:
    if not coord or len(coord) < 3:
        return MISSING
    try:
        deg = float(_ratio(coord[0]))
        minutes = float(_ratio(coord[1]))
        seconds = float(_ratio(coord[2]))
        decimal = deg + minutes / 60.0 + seconds / 3600.0
        if ref in {b"S", "S", b"W", "W"}:
            decimal = -decimal
        return f"{decimal:.8f}"
    except (TypeError, ValueError, ZeroDivisionError):
        return MISSING


def _heic_primary_dimensions(data: bytes) -> tuple[int, int] | None:
    sizes: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = data.find(b"ispe", start)
        if idx < 0:
            break
        if idx >= 4:
            box_size = int.from_bytes(data[idx - 4 : idx], "big")
            if box_size == 20 and idx + 16 <= len(data):
                width = int.from_bytes(data[idx + 8 : idx + 12], "big")
                height = int.from_bytes(data[idx + 12 : idx + 16], "big")
                if 32 <= width <= 30000 and 32 <= height <= 30000:
                    sizes.append((width, height))
        start = idx + 4
    if not sizes:
        return None
    return max(sizes, key=lambda item: item[0] * item[1])


def _heic_exif_tiff(data: bytes) -> bytes | None:
    start = 0
    while True:
        idx = data.find(b"Exif\x00\x00", start)
        if idx < 0:
            return None
        tiff = data[idx + 6 :]
        if tiff[:4] in {b"MM\x00*", b"II*\x00"}:
            return tiff
        start = idx + 4


def _inspect_heic_container(path: Path, info: ImageInfo) -> tuple[ImageInfo, ValidationStatus]:
    data = path.read_bytes()
    dims = _heic_primary_dimensions(data)
    if dims:
        info.pixel_width, info.pixel_height = dims
        info.image_format = "HEIC"
    tiff = _heic_exif_tiff(data)
    if tiff is None or Image is None:
        info.has_exif = False
        if dims:
            return info, ValidationStatus.MISSING_METADATA
        return info, ValidationStatus.UNSUPPORTED_DECODE
    try:
        exif = Image.Exif()
        exif.load(tiff)
    except Exception:
        info.has_exif = False
        if dims:
            return info, ValidationStatus.MISSING_METADATA
        return info, ValidationStatus.UNSUPPORTED_DECODE
    return _apply_exif(info, exif)


def _apply_exif(info: ImageInfo, exif) -> tuple[ImageInfo, ValidationStatus]:
    named = _exif_named(exif)
    if not named:
        info.has_exif = False
        if isinstance(info.pixel_width, int) and isinstance(info.pixel_height, int):
            return info, ValidationStatus.MISSING_METADATA
        return info, ValidationStatus.MISSING_METADATA

    info.has_exif = True
    info.camera_make = str(named["Make"]).strip() if "Make" in named else MISSING
    info.camera_model = str(named["Model"]).strip() if "Model" in named else MISSING
    info.focal_length = _ratio(named["FocalLength"]) if "FocalLength" in named else MISSING
    info.focal_length_35mm = (
        str(named["FocalLengthIn35mmFilm"]) if "FocalLengthIn35mmFilm" in named else MISSING
    )
    info.capture_timestamp = str(named["DateTimeOriginal"]) if "DateTimeOriginal" in named else (
        str(named["DateTime"]) if "DateTime" in named else MISSING
    )
    info.orientation = str(named["Orientation"]) if "Orientation" in named else MISSING
    if "LensModel" in named:
        info.lens_model = str(named["LensModel"]).strip()

    gps = {}
    try:
        gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
        gps = {ExifTags.GPSTAGS.get(key, str(key)): value for key, value in gps_ifd.items()}
    except Exception:
        gps = {}

    if gps:
        info.gps_latitude = _gps_to_degrees(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
        info.gps_longitude = _gps_to_degrees(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
        alt = gps.get("GPSAltitude")
        info.gps_altitude = _ratio(alt) if alt is not None else MISSING
        ref = gps.get("GPSAltitudeRef")
        if info.gps_altitude != MISSING and ref in {1, b"\x01"}:
            info.gps_altitude = f"-{info.gps_altitude}"
    else:
        info.gps_latitude = MISSING
        info.gps_longitude = MISSING
        info.gps_altitude = MISSING

    return info, ValidationStatus.OK


def inspect_image(path: Path, signature: str) -> tuple[ImageInfo, ValidationStatus]:
    info = ImageInfo(image_format=signature if signature.startswith("image/") else MISSING)
    ext = path.suffix.lower()
    if ext in {".heic", ".heif"} and "heic" not in signature:
        info.image_format = "image/heic-candidate"
    if ext == ".dng":
        info.image_format = "image/dng"

    if ext in {".raw", ".cr2", ".nef", ".arw", ".raf", ".orf"}:
        return info, ValidationStatus.UNSUPPORTED_DECODE

    if Image is None:
        if ext in {".heic", ".heif"} or signature == "image/heic":
            return _inspect_heic_container(path, info)
        return info, ValidationStatus.UNSUPPORTED_DECODE

    try:
        with Image.open(path) as img:
            info.pixel_width = int(img.size[0])
            info.pixel_height = int(img.size[1])
            info.image_format = img.format or info.image_format
            exif = img.getexif()
    except Exception:
        if ext in {".heic", ".heif"} or signature == "image/heic":
            return _inspect_heic_container(path, info)
        if signature.startswith("image/"):
            return info, ValidationStatus.UNSUPPORTED_DECODE
        return info, ValidationStatus.UNREADABLE

    return _apply_exif(info, exif)


def _exif_named(exif) -> dict[str, Any]:
    if not exif:
        return {}
    named = {ExifTags.TAGS.get(key, str(key)): value for key, value in exif.items()}
    try:
        extra = exif.get_ifd(ExifTags.IFD.Exif)
        for key, value in extra.items():
            name = ExifTags.TAGS.get(key, str(key))
            named.setdefault(name, value)
    except Exception:
        pass
    return named
