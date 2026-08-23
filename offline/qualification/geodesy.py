"""WGS-84 / UTM helpers for qualification only. No data is rewritten."""

from __future__ import annotations

import math

WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
UTM_K0 = 0.9996


def utm_epsg_to_zone(epsg: str) -> tuple[int, bool] | None:
    if not epsg.startswith("EPSG:"):
        return None
    try:
        code = int(epsg.split(":", 1)[1])
    except ValueError:
        return None
    if 32601 <= code <= 32660:
        return code - 32600, True
    if 32701 <= code <= 32760:
        return code - 32700, False
    return None


def geographic_to_ecef(lat_deg: float, lon_deg: float, height_m: float) -> tuple[float, float, float]:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + height_m) * cos_lat * math.cos(lon)
    y = (n + height_m) * cos_lat * math.sin(lon)
    z = (n * (1.0 - WGS84_E2) + height_m) * sin_lat
    return x, y, z


def utm_to_geographic(easting: float, northing: float, zone: int, northern: bool) -> tuple[float, float]:
    e1 = (1 - math.sqrt(1 - WGS84_E2)) / (1 + math.sqrt(1 - WGS84_E2))
    if not northern:
        northing = northing - 10000000.0
    m = northing / UTM_K0
    mu = m / (WGS84_A * (1 - WGS84_E2 / 4 - 3 * WGS84_E2**2 / 64 - 5 * WGS84_E2**3 / 256))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
    )
    sin_p = math.sin(phi1)
    cos_p = math.cos(phi1)
    tan_p = math.tan(phi1)
    e_prime2 = WGS84_E2 / (1 - WGS84_E2)
    n1 = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_p * sin_p)
    t1 = tan_p * tan_p
    c1 = e_prime2 * cos_p * cos_p
    r1 = WGS84_A * (1 - WGS84_E2) / (1 - WGS84_E2 * sin_p * sin_p) ** 1.5
    d = (easting - 500000.0) / (n1 * UTM_K0)
    lat = phi1 - (n1 * tan_p / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * e_prime2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * e_prime2 - 3 * c1 * c1) * d**6 / 720
    )
    lon0 = math.radians(zone * 6 - 183)
    lon = lon0 + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * e_prime2 + 24 * t1 * t1) * d**5 / 120
    ) / cos_p
    return math.degrees(lat), math.degrees(lon)


def geographic_to_utm(lat_deg: float, lon_deg: float, zone: int) -> tuple[float, float]:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    lon0 = math.radians(zone * 6 - 183)
    e_prime2 = WGS84_E2 / (1 - WGS84_E2)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(lat) ** 2)
    t = math.tan(lat) ** 2
    c = e_prime2 * math.cos(lat) ** 2
    a = math.cos(lat) * (lon - lon0)
    m = WGS84_A * (
        (1 - WGS84_E2 / 4 - 3 * WGS84_E2**2 / 64 - 5 * WGS84_E2**3 / 256) * lat
        - (3 * WGS84_E2 / 8 + 3 * WGS84_E2**2 / 32 + 45 * WGS84_E2**3 / 1024) * math.sin(2 * lat)
        + (15 * WGS84_E2**2 / 256 + 45 * WGS84_E2**3 / 1024) * math.sin(4 * lat)
        - (35 * WGS84_E2**3 / 3072) * math.sin(6 * lat)
    )
    easting = (
        UTM_K0
        * n
        * (
            a
            + (1 - t + c) * a**3 / 6
            + (5 - 18 * t + t * t + 72 * c - 58 * e_prime2) * a**5 / 120
        )
        + 500000.0
    )
    northing = UTM_K0 * (
        m
        + n
        * math.tan(lat)
        * (
            a * a / 2
            + (5 - t + 9 * c + 4 * c * c) * a**4 / 24
            + (61 - 58 * t + t * t + 600 * c - 330 * e_prime2) * a**6 / 720
        )
    )
    return easting, northing


def hypot3(ax: float, ay: float, az: float, bx: float, by: float, bz: float) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)
