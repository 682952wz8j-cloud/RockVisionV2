"""Catalog GPS fields for WallCandidateSelector. Never used for pose."""

from __future__ import annotations

import math

CATALOG_LOCATION_PURPOSE = "wall_candidate_selection_only"
MAX_CANDIDATE_DISTANCE_METERS = 2500.0

# Frozen Jinshidong catalog location: UTM 50N SRS origin from the verified
# wall_build run converted to WGS84. Coarse wall selection only.
JINSHIDONG_WALL_ID = "wall_jinshidong_01"
JINSHIDONG_DISPLAY_NAME = "金狮洞"
JINSHIDONG_CATALOG_LOCATION = {
    "purpose": CATALOG_LOCATION_PURPOSE,
    "latitudeDeg": 30.623418333479282,
    "longitudeDeg": 118.72756872205237,
    "altitudeMeters": 211.89499999933113,
}


class CatalogLocationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def decode_catalog_location(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise CatalogLocationError("CATALOG_LOCATION_INVALID", "catalogLocation must be an object")
    if payload.get("purpose") != CATALOG_LOCATION_PURPOSE:
        raise CatalogLocationError("CATALOG_LOCATION_INVALID", "catalogLocation.purpose is not wall_candidate_selection_only")
    lat = payload.get("latitudeDeg")
    lon = payload.get("longitudeDeg")
    if not _finite_deg(lat, -90.0, 90.0):
        raise CatalogLocationError("CATALOG_LOCATION_INVALID", "catalogLocation.latitudeDeg is invalid")
    if not _finite_deg(lon, -180.0, 180.0):
        raise CatalogLocationError("CATALOG_LOCATION_INVALID", "catalogLocation.longitudeDeg is invalid")
    location = {
        "purpose": CATALOG_LOCATION_PURPOSE,
        "latitudeDeg": float(lat),
        "longitudeDeg": float(lon),
    }
    if "altitudeMeters" in payload:
        alt = payload.get("altitudeMeters")
        if not isinstance(alt, (int, float)) or isinstance(alt, bool) or not math.isfinite(float(alt)):
            raise CatalogLocationError("CATALOG_LOCATION_INVALID", "catalogLocation.altitudeMeters is invalid")
        location["altitudeMeters"] = float(alt)
    return location


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def select_wall_id(
    *,
    latitude_deg: float,
    longitude_deg: float,
    walls: list[dict],
    max_distance_meters: float = MAX_CANDIDATE_DISTANCE_METERS,
) -> str | None:
    """Nearest catalog wall within the coarse GPS radius. No pose."""
    if not _finite_deg(latitude_deg, -90.0, 90.0) or not _finite_deg(longitude_deg, -180.0, 180.0):
        return None
    best_id: str | None = None
    best_distance = max_distance_meters
    for item in walls:
        raw = item.get("catalogLocation")
        if raw is None:
            continue
        location = decode_catalog_location(raw)
        distance = haversine_meters(
            latitude_deg,
            longitude_deg,
            location["latitudeDeg"],
            location["longitudeDeg"],
        )
        wall_id = str(item.get("wallId") or "")
        if not wall_id:
            continue
        if distance <= best_distance:
            if distance < best_distance or best_id is None or wall_id < best_id:
                best_id = wall_id
                best_distance = distance
    return best_id


def _finite_deg(value: object, lo: float, hi: float) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    number = float(value)
    return math.isfinite(number) and lo <= number <= hi
