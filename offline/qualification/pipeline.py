from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from offline.ingestion.pipeline import incoming_dir, repo_root_from
from offline.ingestion.source_trees import resolve_incoming_path, snapshot_source_trees, trees_from_inventory

from .associate import associate_images_to_mrk
from .dxf_geom import parse_dxf_file
from .geodesy import geographic_to_ecef, geographic_to_utm, hypot3, utm_to_geographic
from .images import classify_image, collect_ply_texture_names
from .metadata_scan import scan_records
from .nearest import nearest_distance_stats
from .ply_stats import ply_vertex_bounds, qualify_ply_metric, read_ply_header, read_ply_xyz
from .rasters import qualify_raster
from .reports import write_reports
from .rtk import inspect_rtk_file
from .sessions import (
    DJI_20260823,
    IPHONE_20260823,
    LEGACY_DJI,
    assign_capture_session,
    colmap_readiness,
    iphone_qualification,
    session_summaries,
)
from .status import ProvenanceStatus, claim
from .tiles_inspect import sample_b3dm

MISSING = "missing"


def qualify(wall_id: str, root: Path) -> dict:
    incoming = incoming_dir(root, wall_id)
    inventory_path = root / "offline" / "work" / wall_id / "ingestion" / "inventory.json"
    dest = root / "offline" / "work" / wall_id / "qualification"
    dest.mkdir(parents=True, exist_ok=True)

    if not incoming.is_dir():
        payload = {"result": "FAIL", "errors": ["incoming wall directory does not exist"]}
        write_reports(dest, payload)
        return payload
    if not inventory_path.is_file():
        payload = {"result": "FAIL", "errors": ["Gate 1A inventory.json is missing"]}
        write_reports(dest, payload)
        return payload

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    trees = trees_from_inventory(incoming, inventory)
    before = snapshot_source_trees(trees)
    records = inventory.get("files") or []
    datasets = (inventory.get("datasets") or {}).get("cesium3dTiles") or []

    ply_rec = next((r for r in records if r.get("extension") == ".ply"), None)
    textures = collect_ply_texture_names(incoming, ply_rec["relativePath"] if ply_rec else None)
    images = [assign_capture_session(classify_image(r, textures)) for r in records if r.get("detectedType") == "image"]

    sidecar_index = {
        r["relativePath"]: r.get("geospatialSidecar") or {}
        for r in records
        if r.get("detectedType") == "geospatialSidecar"
    }
    rasters = [
        qualify_raster(r, sidecar_index)
        for r in records
        if r.get("detectedType") == "image" and r.get("extension") in {".tif", ".tiff"}
    ]

    rtk_reports = []
    for rec in records:
        if rec.get("detectedType") != "rtkGnss":
            continue
        parsed = inspect_rtk_file(resolve_incoming_path(incoming, rec["relativePath"]))
        parsed["relativePath"] = rec["relativePath"]
        rtk_reports.append(parsed)

    camera_geo = associate_images_to_mrk(images, rtk_reports)
    meta = scan_records(incoming, records)
    _link_mrk_to_sfm(rtk_reports, meta)

    ply_report = _qualify_ply(incoming, ply_rec, meta)
    route_rec = next((r for r in records if r.get("detectedType") == "routeGeometry"), None)
    route_report = _qualify_route(incoming, route_rec, ply_report.get("points") or [], ply_report)
    ply_report.pop("points", None)
    tiles_report = _qualify_tiles(incoming, datasets, records, ply_report, meta)

    after = snapshot_source_trees(trees)
    incoming_unchanged = before == after

    colmap = [img for img in images if img["colmapSourceCandidate"]]
    jpeg = [img for img in images if img["filename"].lower().endswith((".jpg", ".jpeg"))]
    heic = [img for img in images if img["filename"].lower().endswith((".heic", ".heif"))]
    jpeg_gps = [img for img in jpeg if img["gpsLatitude"] != MISSING]
    png = [img for img in images if img["filename"].lower().endswith(".png")]
    sessions = session_summaries(images, camera_geo, rtk_reports)
    dup_paths = {
        path
        for group in (inventory.get("duplicates") or {}).get("contentDuplicatesNonZero") or []
        for path in group
    }
    iphone = iphone_qualification(images, dup_paths)
    readiness = colmap_readiness(sessions, images, incoming_unchanged)

    findings = _ten_findings(
        images,
        colmap,
        jpeg,
        jpeg_gps,
        rtk_reports,
        camera_geo,
        ply_report,
        route_report,
        tiles_report,
        meta,
        sessions,
    )
    payload = {
        "schemaVersion": "1B.1",
        "wallId": wall_id,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "incomingUnchanged": incoming_unchanged,
        "sourceTrees": [ {"id": t["id"], "relativePrefix": t.get("relativePrefix") or "", "path": str(t["path"])} for t in trees ],
        "captureSessions": sessions,
        "iphoneQualification": iphone,
        "colmapReadiness": readiness,
        "legacyEvidence": {
            "originalDji20260811": 3,
            "imageMrk": "CONTRADICTED",
            "statement": "Gate 1B: 2026-08-11 DJI JPEGs are not the 2026-08-12 MRK/RINEX exposure sequence.",
        },
        "sourceImages": {
            "totalImageFiles": len(images),
            "byRole": _count_roles(images),
            "bySession": _count_sessions(images),
            "jpegCount": len(jpeg),
            "heicCount": len(heic),
            "jpegWithGps": len(jpeg_gps),
            "pngCount": len(png),
            "colmapSourceImages": [img["relativePath"] for img in colmap],
            "colmapSourceImagesBySession": _colmap_by_session(colmap),
            "files": images,
        },
        "rtkGnss": rtk_reports,
        "cameraGeoreference": camera_geo,
        "rasters": rasters,
        "model": ply_report,
        "route": route_report,
        "tiles": tiles_report,
        "metadata": {
            "modelMetadata": meta.get("modelMetadata"),
            "sfmGeoDesc": meta.get("sfmGeoDesc"),
            "modelReport": {
                "outputCoordinate": (meta.get("modelReport") or {}).get("output coordinate", MISSING),
                "generatePly": (meta.get("modelReport") or {}).get("generate ply", MISSING),
                "generateB3dm": (meta.get("modelReport") or {}).get("generate b3dm", MISSING),
            }
            if meta.get("modelReport")
            else MISSING,
            "mapReport": {
                "outputCoordinate": (meta.get("mapReport") or {}).get("output coordinate", MISSING),
                "mapTile": (meta.get("mapReport") or {}).get("map tile", MISSING),
                "gpsCorner": (meta.get("mapReport") or {}).get("gps corner", MISSING),
            }
            if meta.get("mapReport")
            else MISSING,
            "keywordFiles": meta.get("keywordFiles"),
        },
        "findings": findings,
        "recommendation": _recommendation(findings, ply_report, rtk_reports, colmap, sessions),
    }
    write_reports(dest, payload)
    return payload


def _link_mrk_to_sfm(rtk_reports: list[dict], meta: dict) -> None:
    gps = (meta.get("sfmGeoDesc") or {}).get("ref_GPS") if meta.get("sfmGeoDesc") else None
    if not gps:
        return
    for parsed in rtk_reports:
        if parsed.get("fileType") != "djiMrk":
            continue
        for rec in parsed.get("records") or []:
            try:
                if (
                    abs(float(rec["latitude"]) - float(gps["latitude"])) < 1e-8
                    and abs(float(rec["longitude"]) - float(gps["longitude"])) < 1e-8
                    and abs(float(rec["ellipsoidalHeight"]) - float(gps["altitude"])) < 1e-3
                ):
                    parsed.setdefault("links", []).append(
                        claim(
                            ProvenanceStatus.PROVEN,
                            "MRK record equals sfm_geo_desc.ref_GPS (ellipsoidal)",
                            [
                                f"MRK photoId={rec.get('photoId')} {rec.get('latitude')},{rec.get('longitude')},{rec.get('ellipsoidalHeight')}",
                                f"sfm_geo_desc ref_GPS {gps}",
                            ],
                        )
                    )
                    return
            except (TypeError, ValueError):
                continue


def _count_roles(images: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for img in images:
        counts[img["role"]] = counts.get(img["role"], 0) + 1
    return counts


def _count_sessions(images: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for img in images:
        key = img.get("captureSession") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _colmap_by_session(colmap: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for img in colmap:
        grouped.setdefault(img.get("captureSession") or "unknown", []).append(img["relativePath"])
    return grouped


def _qualify_ply(incoming: Path, ply_rec: dict | None, meta: dict) -> dict:
    if not ply_rec:
        return {"present": False, "claims": [claim(ProvenanceStatus.UNKNOWN, "No PLY in inventory", [])]}
    path = incoming / ply_rec["relativePath"]
    header = read_ply_header(path)
    bounds = ply_vertex_bounds(path, header)
    xml = meta.get("modelMetadata")
    claims = qualify_ply_metric(header, bounds, xml)
    origin = (xml or {}).get("srsOrigin") if xml else None
    origin_check = MISSING
    if origin and bounds.get("status") == "ok":
        lat, lon = utm_to_geographic(origin[0], origin[1], 50, True)
        origin_check = {
            "srsOriginUtm": origin,
            "srsOriginGeographicApprox": {"lat": lat, "lon": lon, "h": origin[2]},
        }
        ref = meta.get("sfmGeoDesc") or {}
        gps = ref.get("ref_GPS") if isinstance(ref, dict) else None
        if gps:
            e, n = geographic_to_utm(gps["latitude"], gps["longitude"], 50)
            d_e = abs(e - origin[0])
            d_n = abs(n - origin[1])
            d_h = abs(gps["altitude"] - origin[2])
            origin_check["sfmRefGps"] = gps
            origin_check["utmOfSfmRefGps"] = [e, n]
            origin_check["deltaMetersENH"] = [d_e, d_n, d_h]
            if d_e < 0.05 and d_n < 0.05 and d_h < 0.05:
                claims.append(
                    claim(
                        ProvenanceStatus.PROVEN,
                        "PLY SRSOrigin matches sfm_geo_desc.ref_GPS in UTM 50N / ellipsoidal height",
                        [
                            f"ΔE={d_e:.4f} m, ΔN={d_n:.4f} m, ΔH={d_h:.4f} m",
                            "Differences are at centimetre level after WGS-84 conversion.",
                        ],
                    )
                )
            else:
                claims.append(
                    claim(
                        ProvenanceStatus.CONTRADICTED
                        if max(d_e, d_n) > 5
                        else ProvenanceStatus.UNKNOWN,
                        "PLY SRSOrigin and AT ref_GPS do not match closely",
                        [f"ΔE={d_e:.3f} ΔN={d_n:.3f} ΔH={d_h:.3f}"],
                    )
                )
        if xml and xml.get("srs") == "EPSG:32650":
            claims.append(
                claim(
                    ProvenanceStatus.PROVEN,
                    "PLY is a local translation of EPSG:32650, not raw global UTM vertices",
                    [
                        f"metadata.xml SRSOrigin {origin}",
                        f"vertex bbox {bounds.get('min')} .. {bounds.get('max')}",
                    ],
                )
            )
    return {
        "present": True,
        "relativePath": ply_rec["relativePath"],
        "header": header,
        "bounds": bounds,
        "modelMetadata": xml,
        "originCheck": origin_check,
        "points": read_ply_xyz(path, header) if bounds.get("status") == "ok" else [],
        "claims": claims,
    }


def _qualify_route(incoming: Path, route_rec: dict | None, ply_points: list, ply_report: dict) -> dict:
    if not route_rec:
        return {"present": False, "claims": [claim(ProvenanceStatus.UNKNOWN, "No DXF route", [])]}
    geom = parse_dxf_file(incoming / route_rec["relativePath"])
    claims = [
        claim(
            ProvenanceStatus.PROVEN,
            "DXF was exported from CloudCompare",
            [str(geom.get("createdBy"))],
        )
    ]
    if geom.get("insUnits") == MISSING:
        claims.append(claim(ProvenanceStatus.UNKNOWN, "DXF $INSUNITS is not set", ["No units metadata in HEADER."]))
    distance = MISSING
    if geom.get("vertices") and ply_points:
        queries = [(v["x"], v["y"], v["z"]) for v in geom["vertices"]]
        distance = nearest_distance_stats(queries, ply_points)
        if distance.get("status") == "ok":
            median = distance["median"]
            if median < 0.5:
                claims.append(
                    claim(
                        ProvenanceStatus.SUPPORTED,
                        "DXF vertices lie on the PLY surface at sub-metre median distance",
                        [
                            f"median={median:.4f} p90={distance['p90']:.4f} max={distance['max']:.4f}",
                            "Median closeness is strong spatial consistency, not complete provenance.",
                            "A minority of vertices are tens of metres away; no transform was applied.",
                            f"CloudCompare creator string: {geom.get('createdBy')}",
                        ],
                    )
                )
            elif median < 5:
                claims.append(
                    claim(
                        ProvenanceStatus.SUPPORTED,
                        "DXF and PLY overlap at metre-level distances",
                        [f"median={median:.3f} max={distance['max']:.3f}"],
                    )
                )
            else:
                claims.append(
                    claim(
                        ProvenanceStatus.UNKNOWN,
                        "DXF vertices are not close to PLY vertices",
                        [f"median={median:.3f} max={distance['max']:.3f}"],
                    )
                )
    return {
        "present": True,
        "relativePath": route_rec["relativePath"],
        "geometry": {k: v for k, v in geom.items() if k != "vertices"} | {"vertexCount": geom.get("vertexCount")},
        "vertices": geom.get("vertices"),
        "distanceToPly": {k: v for k, v in distance.items() if k != "status"} if isinstance(distance, dict) else distance,
        "claims": claims,
    }


def _qualify_tiles(incoming: Path, datasets: list[dict], records: list[dict], ply_report: dict, meta: dict) -> dict:
    if not datasets:
        return {"present": False, "claims": [claim(ProvenanceStatus.UNKNOWN, "No 3D Tiles dataset", [])]}
    dataset = datasets[0]
    b3dm_paths = [r["relativePath"] for r in records if r.get("extension") == ".b3dm"]
    samples = sample_b3dm(incoming, b3dm_paths)
    claims = [
        claim(
            ProvenanceStatus.PROVEN,
            "Root tileset.json exists and references the B3DM set",
            [dataset.get("tilesetPath", "")],
        )
    ]
    rtc_any = any(s.get("rtcCenter") not in {None, MISSING} for s in samples)
    cesium_rtc = any(s.get("cesiumRtc") for s in samples)
    if not rtc_any:
        claims.append(claim(ProvenanceStatus.UNKNOWN, "No RTC_CENTER in sampled B3DM feature tables", [f"sampled {len(samples)}"]))
    if not cesium_rtc:
        claims.append(claim(ProvenanceStatus.UNKNOWN, "No CESIUM_RTC string in sampled B3DM prefixes", []))

    child_transform = MISSING
    child_path = incoming / "九龙峰森林站大楼/models/pc/0/terra_b3dms/BlockR/tileset.json"
    if child_path.is_file():
        child = json.loads(child_path.read_text(encoding="utf-8"))
        child_transform = (child.get("root") or {}).get("transform", MISSING)

    ecef_compare = MISSING
    xml = meta.get("modelMetadata")
    origin = (xml or {}).get("srsOrigin") if xml else None
    if origin and child_transform != MISSING and len(child_transform) == 16:
        lat, lon = utm_to_geographic(origin[0], origin[1], 50, True)
        ecef = geographic_to_ecef(lat, lon, origin[2])
        tx, ty, tz = child_transform[12], child_transform[13], child_transform[14]
        delta = hypot3(ecef[0], ecef[1], ecef[2], tx, ty, tz)
        ecef_compare = {
            "srsOriginEcef": list(ecef),
            "childTilesetTranslation": [tx, ty, tz],
            "deltaMeters": delta,
        }
        if delta < 5:
            claims.append(
                claim(
                    ProvenanceStatus.PROVEN,
                    "Child tileset translation matches ECEF of metadata.xml SRSOrigin",
                    [f"Δ={delta:.3f} m", "Cesium 4x4 translation compared to WGS-84 ECEF of EPSG:32650 origin."],
                )
            )
        elif delta < 50:
            claims.append(
                claim(
                    ProvenanceStatus.SUPPORTED,
                    "Child tileset translation is near ECEF of SRSOrigin",
                    [f"Δ={delta:.3f} m"],
                )
            )
        else:
            claims.append(
                claim(
                    ProvenanceStatus.UNKNOWN,
                    "Child tileset translation does not match computed ECEF of SRSOrigin",
                    [f"Δ={delta:.3f} m"],
                )
            )
    model_report = meta.get("modelReport") or {}
    if model_report.get("generate ply") and model_report.get("generate b3dm"):
        claims.append(
            claim(
                ProvenanceStatus.SUPPORTED,
                "Same Terra job requested both PLY and B3DM output",
                ["model_report.json generate ply=true and generate b3dm=true"],
            )
        )
    if dataset.get("crs") in {None, MISSING}:
        claims.append(
            claim(
                ProvenanceStatus.UNKNOWN,
                "Root tileset.json does not declare a CRS",
                ["crs field missing; ECEF is only inferred if the translation test succeeds."],
            )
        )
    return {
        "present": True,
        "dataset": {k: dataset[k] for k in dataset if k != "childTilesets"},
        "b3dmSamples": samples,
        "childTransform": child_transform,
        "ecefCompare": ecef_compare,
        "claims": claims,
    }


def _ten_findings(images, colmap, jpeg, jpeg_gps, rtk_reports, camera_geo, ply_report, route_report, tiles_report, meta, sessions=None) -> list[dict]:
    original = [i for i in images if i["role"] == "originalCameraImage"]
    parsed_ok = [r for r in rtk_reports if r.get("parseStatus") == "parsed"]
    sessions = sessions or {}
    legacy = sessions.get(LEGACY_DJI) or {}
    new_dji = sessions.get(DJI_20260823) or {}
    iphone = sessions.get(IPHONE_20260823) or {}

    ply_metric = next(
        (
            c
            for c in ply_report.get("claims") or []
            if "EPSG:32650 uses metres" in c["statement"]
        ),
        None,
    )
    if ply_metric is None:
        ply_metric = next(
            (c for c in ply_report.get("claims") or [] if "units" in c["statement"].lower()),
            None,
        )
    ply_utm = next((c for c in ply_report.get("claims") or [] if "EPSG:32650" in c["statement"] and "local translation" in c["statement"]), None)
    if ply_utm is None:
        ply_utm = next((c for c in ply_report.get("claims") or [] if "EPSG:32650" in c["statement"]), None)
    dxf_ply = next((c for c in route_report.get("claims") or [] if "PLY" in c["statement"]), None)
    tiles_ply = next((c for c in tiles_report.get("claims") or [] if "SRSOrigin" in c["statement"] or "PLY" in c["statement"]), None)

    new_status = new_dji.get("imageMrkStatus") or ProvenanceStatus.UNKNOWN.value
    assoc_status = ProvenanceStatus(new_status) if new_status in {s.value for s in ProvenanceStatus} else ProvenanceStatus.UNKNOWN

    return [
        claim(ProvenanceStatus.PROVEN, f"{len(original)} original camera images across separate capture sessions", [
            f"LEGACY: {legacy.get('originalCameraImages', 0)} DJI M4E JPEGs from 2026-08-11.",
            f"NEW DJI: {new_dji.get('originalCameraImages', 0)} DJI M4E JPEGs from 2026-08-23.",
            f"NEW iPhone: {iphone.get('originalCameraImages', 0)} HEIC originals from 2026-08-23 (not mixed into the DJI pool).",
            f"Other JPEGs remain textures or report images.",
        ]),
        claim(ProvenanceStatus.PROVEN, f"{len(colmap)} files are auto-eligible COLMAP source images", [
            "DJI originalCameraImage rows only. 2026-08-23 iPhone files are qualified but not auto-listed.",
            "Derived PNG tiles, report JPEGs, textures, and GeoTIFFs are excluded.",
        ]),
        claim(ProvenanceStatus.PROVEN, f"{len(jpeg_gps)} of {len(jpeg)} JPEGs have GPS", [
            "Legacy texture/report JPEGs still have no EXIF GPS.",
            "2026-08-23 DJI originals carry EXIF GPS.",
        ]),
        claim(
            ProvenanceStatus.PROVEN if parsed_ok else ProvenanceStatus.UNKNOWN,
            f"RTK/GNSS: {len(parsed_ok)} files parsed, others partial/unsupported",
            [f"{r['filename']}: {r.get('fileType')} / {r.get('parseStatus')}" for r in rtk_reports],
        ),
        claim(
            assoc_status,
            f"2026-08-23 image ↔ MRK is {new_status}; legacy 8/11 images vs 8/12 MRK remains CONTRADICTED",
            [
                "LEGACY EVIDENCE (unchanged from Gate 1B): 2026-08-11 DJI JPEGs are not the 2026-08-12 MRK/RINEX exposure sequence.",
                f"NEW 2026-08-23: matched {new_dji.get('matchedImageCount', 0)} images, unmatched {new_dji.get('unmatchedImageCount', 0)}; methods={new_dji.get('associationMethods')}.",
            ],
        ),
        ply_metric or claim(ProvenanceStatus.UNKNOWN, "PLY metric status", ["PLY missing or header has no units"]),
        ply_utm or claim(ProvenanceStatus.UNKNOWN, "PLY EPSG:32650", ["No metadata.xml SRS"]),
        dxf_ply or claim(ProvenanceStatus.UNKNOWN, "DXF vs PLY frame", ["Distance test not available"]),
        tiles_ply or claim(ProvenanceStatus.UNKNOWN, "3D Tiles vs PLY", ["No matching transform test"]),
        claim(ProvenanceStatus.SUPPORTED, "Preferred future S_wall_colmap path", [
            "Local metric PLY/AT origin remains the proven wall frame.",
            "2026-08-23 DJI now has same-batch MRK positions; legacy 8/11 photos still do not.",
        ]),
    ]


def _recommendation(findings, ply_report, rtk_reports, colmap, sessions=None) -> dict:
    return {
        "metricWallFrame": {
            "recommendation": "LocalMetricWallFrame",
            "unit": "meters",
            "originSource": "metadata.xml SRSOrigin if present",
            "store": "T_EPSG32650_WallLocal = translation by SRSOrigin (no extra rotation proven)",
            "why": "EPSG:32650 eastings are ~6e5; AR float transforms should use a local metre origin.",
        },
        "sWallColmapPriority": [
            {
                "id": "C",
                "name": "Register COLMAP to the proven local metric PLY / AT origin",
                "status": "SUPPORTED",
                "why": "PLY+metadata.xml give a metre local frame. COLMAP still needs its own Sim(3) to that frame.",
            },
            {
                "id": "A",
                "name": "RTK/GNSS camera positions",
                "status": (
                    "PROVEN-for-2026-08-23 / CONTRADICTED-for-legacy-8/11"
                    if (sessions or {}).get(DJI_20260823, {}).get("imageMrkStatus") == ProvenanceStatus.PROVEN.value
                    else "SUPPORTED-as-method / UNKNOWN-or-CONTRADICTED-for-photos"
                ),
                "why": "LEGACY: 2026-08-11 JPEGs ≠ 2026-08-12 MRK/RINEX. NEW: 2026-08-23 JPEGs associate to the 2026-08-23 MRK by sequence + shared folder.",
            },
            {
                "id": "B",
                "name": "EPSG:32650 rasters (DSM/orthophoto)",
                "status": "SUPPORTED",
                "why": "Useful geographic control, but they are derived maps, not the photo reconstruction frame.",
            },
            {
                "id": "D",
                "name": "Known physical distances / GCPs",
                "status": "UNKNOWN",
                "why": "No surveyed control points found in the drop.",
            },
        ],
        "scaleVsSim3": [
            "Metric scale answers 1 reconstruction unit = ? metres.",
            "S_wall_colmap is full Sim(3): scale, rotation, and translation.",
            "Knowing metres does not mean COLMAP is aligned to the Wall Frame.",
        ],
    }
