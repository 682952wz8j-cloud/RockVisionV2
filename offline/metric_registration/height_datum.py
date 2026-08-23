"""Re-verify ellipsoidal height consistency. Do not invent a Z offset."""

from __future__ import annotations

import json
from pathlib import Path

from offline.qualification.geodesy import geographic_to_utm
from offline.qualification.rtk import parse_mrk

from .frames import UTM_EPSG, geodetic_to_projected_metric

SFM_GEO_DESC = "九龙峰森林站大楼/AT/sfm_geo_desc.json"
LEGACY_MRK = "dji_flight_raw_jiulongfeng/rtk_ppk_004/DJI_20260812152955_0002_D.MRK"


def verify_height_datum(incoming_wall: Path, origin: list[float]) -> dict:
    sfm_path = incoming_wall / SFM_GEO_DESC
    sfm = json.loads(sfm_path.read_text(encoding="utf-8"))
    gps = sfm["ref_GPS"]
    easting, northing = geographic_to_utm(gps["latitude"], gps["longitude"], 50)
    d_e = abs(easting - origin[0])
    d_n = abs(northing - origin[1])
    d_h = abs(float(gps["altitude"]) - origin[2])

    legacy = parse_mrk((incoming_wall / LEGACY_MRK).read_text(encoding="utf-8", errors="replace"))
    match = None
    for rec in legacy.get("records") or []:
        try:
            if (
                abs(float(rec["latitude"]) - float(gps["latitude"])) < 1e-7
                and abs(float(rec["longitude"]) - float(gps["longitude"])) < 1e-7
                and abs(float(rec["ellipsoidalHeight"]) - float(gps["altitude"])) < 1e-3
            ):
                match = {
                    "photoId": rec.get("photoId"),
                    "ellipsoidalHeight": rec.get("ellipsoidalHeight"),
                    "heightDatum": rec.get("heightDatum"),
                    "sourceFile": LEGACY_MRK,
                }
                break
        except (TypeError, ValueError):
            continue

    mixed = False
    problems = []
    if d_e > 0.05 or d_n > 0.05 or d_h > 0.05:
        mixed = True
        problems.append(
            f"SRSOrigin vs sfm_geo_desc.ref_GPS mismatch ΔE={d_e:.4f} ΔN={d_n:.4f} ΔH={d_h:.4f}"
        )
    if match is None:
        mixed = True
        problems.append("Could not re-prove sfm_geo_desc.ref_GPS equals a legacy MRK Ellh record")
    elif match.get("heightDatum") != "ellipsoidal":
        mixed = True
        problems.append("Matched MRK record is not labeled ellipsoidal")

    return {
        "heightDatumUsed": "ellipsoidal",
        "srsOrigin": origin,
        "sfmGeoDescRefGps": gps,
        "sfmFieldName": "altitude",
        "sfmFieldInterpretation": (
            "JSON key is 'altitude'; numerically identical to the matching MRK Ellh "
            "and to metadata.xml SRSOrigin Z. Treated as ellipsoidal height, not orthometric."
        ),
        "utmOfSfmRefGps": [easting, northing, float(gps["altitude"])],
        "deltaMetersENH": [d_e, d_n, d_h],
        "legacyMrkMatch": match,
        "horizontalCrs": UTM_EPSG,
        "mixedDatumDetected": mixed,
        "problems": problems,
        "noGeoidOffsetApplied": True,
    }


def projected_from_mrk_record(rec: dict) -> list[float]:
    metric = geodetic_to_projected_metric(rec["latitude"], rec["longitude"], rec["ellipsoidalHeight"])
    return metric.tolist()
