"""Build the unpublished Jiulongfeng production release candidate.

Reuses the frozen Aug 23 COLMAP, baseline_2px Stage 3, and VALIDATED Sim(3).
Does not reconstruct COLMAP. Does not redraw routes. Does not publish.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from offline.catalog_promotion.location import (
    JIULONGFENG_CATALOG_LOCATION,
    JIULONGFENG_DISPLAY_NAME,
    JIULONGFENG_WALL_ID as _LOCATION_WALL_ID,
)
from offline.colmap.source_identity import (
    PROVENANCE_ORIGIN_RECONSTRUCTION_RUN,
    SELECTED_MODEL_RELATIVE_PATH,
    build_provenance_payload,
    model_fingerprint,
    read_registered_names,
)
from offline.localization_package.cloud_manifest import local_cloud_manifest
from offline.localization_package.layout import (
    asset_path,
    cloud_manifest_path,
    evidence_path,
    package_dir,
    package_json_path,
)
from offline.localization_package.package_schema import is_release_id
from offline.localization_package.schema import (
    COLMAP_IDENTITY_PROVEN,
    ENVIRONMENT_PRODUCTION,
    PACKAGE_SCHEMA,
    STATE_PACKAGE_READY,
    TYPE_DESCRIPTORS,
    TYPE_LANDMARKS,
    TYPE_S_WALL_COLMAP,
)
from offline.localization_package.validate import validate_package_dir
from offline.route_ingestion.production_asset import (
    ASSET_ID as ROUTES_ASSET_ID,
    EXPECTED_JIULONGFENG_ROUTE_IDS,
    TYPE_WALL_ROUTES,
    build_production_route_asset,
)

JIULONGFENG_WALL_ID = _LOCATION_WALL_ID
JIULONGFENG_RUN_ID = "wb_20260823T130500Z_6ceebb24"
JIULONGFENG_FINGERPRINT = "6ceebb249ec245f0394da46dac94e13bfe29f166d7f2aa11747e66ca4342946f"
PRODUCTION_RELEASE_ID = "r000001"
PRODUCTION_ROUTE_ID = EXPECTED_JIULONGFENG_ROUTE_IDS[0]
PRODUCTION_ROUTE_NAME = "白墙测试线"
FROZEN_POLYLINE_SHA256 = "ff6ff3ee58303634d369b919284ee8c827a80eb57a9403004614cda6194d2f99"
LIVE_PRODUCTION = "https://api.cragpal.com"
_WALL_BUILD_EVIDENCE_RUN = "wb_20260910T140932Z_e5daf3c7"


def frozen_colmap_dir(root: Path) -> Path:
    return root / "offline" / "work" / JIULONGFENG_WALL_ID / "colmap"


def frozen_stage3_dir(root: Path) -> Path:
    return (
        root
        / "offline"
        / "work"
        / JIULONGFENG_WALL_ID
        / "reference_matching"
        / "baseline_2px"
    )


def frozen_sim3_path(root: Path) -> Path:
    return root / "offline" / "work" / JIULONGFENG_WALL_ID / "metric_registration" / "S_wall_colmap.json"


def frozen_ingested_route_path(root: Path) -> Path:
    return root / "validation" / "gate5a" / "gate5a_ingested_route_test_01.json"


def wall_build_evidence_dir(root: Path) -> Path:
    return root / "offline" / "work" / JIULONGFENG_WALL_ID / "wall_build" / _WALL_BUILD_EVIDENCE_RUN


def production_candidate_dir(root: Path, release_id: str = PRODUCTION_RELEASE_ID) -> Path:
    return package_dir(root, JIULONGFENG_WALL_ID, release_id)


def choose_unused_production_release_id(
    root: Path,
    *,
    live_host: str | None = LIVE_PRODUCTION,
    timeout: float = 10.0,
) -> str:
    """First legal production rNNNNNN not already catalogued for this wall."""
    used: set[str] = set()
    if live_host:
        try:
            with urllib.request.urlopen(f"{live_host.rstrip('/')}/v1/walls", timeout=timeout) as response:
                catalog = json.loads(response.read().decode("utf-8"))
            for item in catalog.get("walls") or []:
                if item.get("wallId") != JIULONGFENG_WALL_ID:
                    continue
                rid = item.get("latestReleaseId")
                if is_release_id(str(rid or "")):
                    used.add(str(rid))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            pass
    n = 1
    while n <= 999999:
        rid = f"r{n:06d}"
        if rid not in used:
            return rid
        n += 1
    raise RuntimeError("no unused production release id")


def build_jiulongfeng_production_candidate(
    root: Path,
    *,
    dest: Path | None = None,
    created_at: str | None = None,
    release_id: str | None = None,
) -> dict:
    chosen = release_id or PRODUCTION_RELEASE_ID
    if not is_release_id(chosen):
        raise ValueError(f"invalid production releaseId {chosen}")
    colmap_dir = frozen_colmap_dir(root)
    best = colmap_dir / SELECTED_MODEL_RELATIVE_PATH
    fingerprint = model_fingerprint(best)
    if fingerprint != JIULONGFENG_FINGERPRINT:
        raise ValueError("frozen sparse/best fingerprint mismatch; refusing to remodel")
    stage3 = frozen_stage3_dir(root)
    sim3_src = frozen_sim3_path(root)
    ingested_src = frozen_ingested_route_path(root)
    evidence_run = wall_build_evidence_dir(root)
    for path in (best, stage3 / "descriptors.bin", stage3 / "landmarks.json", sim3_src, ingested_src, evidence_run):
        if not path.exists():
            raise FileNotFoundError(f"missing frozen Jiulongfeng asset {path}")

    jpeg = _selected_jpeg_sha256(colmap_dir)
    identity = _production_identity(colmap_dir, jpeg)
    if identity["modelFingerprint"] != JIULONGFENG_FINGERPRINT:
        raise ValueError("identity fingerprint mismatch")
    selection = json.loads((evidence_run / "stage2_input_selection.json").read_text(encoding="utf-8"))
    if selection.get("wallId") != JIULONGFENG_WALL_ID:
        raise ValueError("stage2 selection wallId mismatch")
    selection = dict(selection)
    selection["runId"] = JIULONGFENG_RUN_ID
    selection["selectedImageSha256"] = dict(jpeg)
    pq = json.loads((evidence_run / "positioning_quality.json").read_text(encoding="utf-8"))
    height = json.loads((evidence_run / "height_vertical_datum.json").read_text(encoding="utf-8"))

    descriptors = (stage3 / "descriptors.bin").read_bytes()
    if descriptors[:4] != b"RVS1":
        raise ValueError("frozen descriptors are not RVS1")
    landmarks = _landmarks_as_wall_package((stage3 / "landmarks.json").read_bytes())
    sim3 = _sim3_with_identity(json.loads(sim3_src.read_text(encoding="utf-8")))
    sim3_bytes = (json.dumps(sim3, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    freeze = dict(json.loads((stage3 / "freeze.json").read_text(encoding="utf-8")))
    freeze["wallId"] = JIULONGFENG_WALL_ID
    freeze["wallBuildRunId"] = JIULONGFENG_RUN_ID
    freeze["colmapModelFingerprint"] = JIULONGFENG_FINGERPRINT
    freeze["landmarksSha256"] = _sha(landmarks)
    freeze["landmarksBytes"] = len(landmarks)
    freeze["descriptorsSha256"] = _sha(descriptors)
    freeze["descriptorsBytes"] = len(descriptors)

    ingested = _production_ingested_route(json.loads(ingested_src.read_text(encoding="utf-8")))
    routes_payload = build_production_route_asset(
        wall_id=JIULONGFENG_WALL_ID,
        release_id=chosen,
        run_id=JIULONGFENG_RUN_ID,
        model_fingerprint=JIULONGFENG_FINGERPRINT,
        ingested_records=[ingested],
    )
    routes_bytes = (json.dumps(routes_payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    desc_spec = {
        "assetId": "stage3-descriptors",
        "type": TYPE_DESCRIPTORS,
        "schema": "RVS1",
        "sha256": _sha(descriptors),
        "bytes": len(descriptors),
    }
    land_spec = {
        "assetId": "stage3-landmarks",
        "type": TYPE_LANDMARKS,
        "schema": 1,
        "sha256": _sha(landmarks),
        "bytes": len(landmarks),
    }
    metric_spec = {
        "assetId": "s-wall-colmap",
        "type": TYPE_S_WALL_COLMAP,
        "status": "VALIDATED",
        "source": "S_wall_colmap.json",
        "sha256": _sha(sim3_bytes),
        "bytes": len(sim3_bytes),
    }
    routes_spec = {
        "assetId": ROUTES_ASSET_ID,
        "type": TYPE_WALL_ROUTES,
        "sha256": _sha(routes_bytes),
        "bytes": len(routes_bytes),
        "present": True,
        "authorized": True,
    }

    package = {
        "schema": PACKAGE_SCHEMA,
        "wallId": JIULONGFENG_WALL_ID,
        "releaseId": chosen,
        "environment": ENVIRONMENT_PRODUCTION,
        "capabilities": {"localizationReady": True, "routeArReady": False},
        "sourceBuild": {
            "runId": JIULONGFENG_RUN_ID,
            "selection": {
                "schema": selection.get("schemaVersion") or "stage2_input_selection.4",
                "selectionStatus": selection.get("selectionStatus"),
            },
            "selectedSourceJpegSha256": jpeg,
            "positioningQuality": {
                "positioningQualityExecutionAllowed": bool(pq.get("positioningQualityExecutionAllowed")),
                "positioningQualityReasonCode": pq.get("positioningQualityReasonCode"),
            },
            "heightDatum": {"heightGateExecutionAllowed": bool(height.get("heightGateExecutionAllowed"))},
            "colmapSourceIdentity": {
                "modelFingerprint": JIULONGFENG_FINGERPRINT,
                "colmapSourceIdentityReasonCode": COLMAP_IDENTITY_PROVEN,
                "colmapSourceIdentityExecutionAllowed": True,
            },
        },
        "metricTransform": metric_spec,
        "stage3": {
            "descriptors": desc_spec,
            "landmarks": land_spec,
            "freezeIdentity": {
                "colmapModelFingerprint": JIULONGFENG_FINGERPRINT,
                "wallBuildRunId": JIULONGFENG_RUN_ID,
            },
        },
        "routes": routes_spec,
        "packageState": STATE_PACKAGE_READY,
        "notACatalogRelease": True,
        "catalogLocation": dict(JIULONGFENG_CATALOG_LOCATION),
        "displayName": JIULONGFENG_DISPLAY_NAME,
    }

    created = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = local_cloud_manifest(
        wall_id=JIULONGFENG_WALL_ID,
        release_id=chosen,
        created_at=created,
        descriptors=desc_spec,
        landmarks=land_spec,
        metric=metric_spec,
        routes=routes_spec,
    )

    dest_root = dest if dest is not None else production_candidate_dir(root, chosen)
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    (dest_root / "assets").mkdir(parents=True, exist_ok=True)
    (dest_root / "evidence").mkdir(parents=True, exist_ok=True)
    asset_path(dest_root, "stage3-descriptors").write_bytes(descriptors)
    asset_path(dest_root, "stage3-landmarks").write_bytes(landmarks)
    asset_path(dest_root, "s-wall-colmap").write_bytes(sim3_bytes)
    asset_path(dest_root, ROUTES_ASSET_ID).write_bytes(routes_bytes)
    evidence_path(dest_root, "stage2_input_selection.json").write_text(
        json.dumps(selection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    evidence_path(dest_root, "positioning_quality.json").write_text(
        json.dumps(pq, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    evidence_path(dest_root, "height_vertical_datum.json").write_text(
        json.dumps(height, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    evidence_path(dest_root, "colmap_source_identity.json").write_text(
        json.dumps(identity, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    evidence_path(dest_root, "freeze.json").write_text(
        json.dumps(freeze, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    package_json_path(dest_root).write_text(json.dumps(package, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cloud_manifest_path(dest_root).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    result = validate_package_dir(dest_root)
    if not result.ok or result.package_state != STATE_PACKAGE_READY or not result.localization_ready:
        raise ValueError(f"production candidate is not PACKAGE_READY: {result.reason_codes}")
    if result.release_id != chosen or result.wall_id != JIULONGFENG_WALL_ID:
        raise ValueError("production candidate identity mismatch")
    routes = json.loads(asset_path(dest_root, ROUTES_ASSET_ID).read_text(encoding="utf-8"))
    return {
        "packageDir": str(dest_root),
        "wallId": JIULONGFENG_WALL_ID,
        "releaseId": chosen,
        "runId": JIULONGFENG_RUN_ID,
        "colmapModelFingerprint": JIULONGFENG_FINGERPRINT,
        "displayName": JIULONGFENG_DISPLAY_NAME,
        "catalogLocation": dict(JIULONGFENG_CATALOG_LOCATION),
        "routeId": PRODUCTION_ROUTE_ID,
        "routeName": PRODUCTION_ROUTE_NAME,
        "polylineSha256": routes["routes"][0]["polylineSha256"],
        "packageState": result.package_state,
        "localizationReady": result.localization_ready,
        "routeArReady": result.route_ar_ready,
        "reasonCodes": result.reason_codes,
        "metricType": TYPE_S_WALL_COLMAP,
        "routesAssetId": ROUTES_ASSET_ID,
        "published": False,
        "catalogDiscoverable": False,
    }


def _selected_jpeg_sha256(colmap_dir: Path) -> dict[str, str]:
    manifest = json.loads((colmap_dir / "colmap_source_manifest.json").read_text(encoding="utf-8"))
    images = manifest.get("images") or []
    jpeg = {item["relativePath"]: item["sha256Incoming"] for item in images}
    if len(jpeg) != 47:
        raise ValueError("frozen COLMAP source is not the 47-image capture")
    return jpeg


def _production_identity(colmap_dir: Path, jpeg: dict[str, str]) -> dict:
    best = colmap_dir / SELECTED_MODEL_RELATIVE_PATH
    registered = read_registered_names(best)
    payload = build_provenance_payload(
        wall_id=JIULONGFENG_WALL_ID,
        selected_relative_paths=tuple(jpeg.keys()),
        selected_sha256=jpeg,
        selected_model_id=0,
        selected_model_relative_path=SELECTED_MODEL_RELATIVE_PATH,
        source_model_relative_path="sparse/0",
        registered_image_names=registered,
        model_dir=best,
        image_dir_relative="DJI_202608231218_006_九龙峰",
        provenance_origin=PROVENANCE_ORIGIN_RECONSTRUCTION_RUN,
    )
    payload["generatedAt"] = "2026-08-23T13:05:00+00:00"
    payload["colmapSourceIdentityExecutionAllowed"] = True
    payload["colmapSourceIdentityReasonCode"] = COLMAP_IDENTITY_PROVEN
    return payload


def _landmarks_as_wall_package(raw: bytes) -> bytes:
    text = raw.decode("utf-8")
    if '"developmentFixtureOnly":true' not in text or '"notAWallPackage":true' not in text:
        raise ValueError("frozen landmarks are missing fixture identity flags")
    converted = text.replace('"developmentFixtureOnly":true,', "", 1).replace('"notAWallPackage":true,', "", 1)
    if '"developmentFixtureOnly"' in converted or '"notAWallPackage"' in converted:
        raise ValueError("failed to convert landmarks to WallPackage identity")
    return converted.encode("utf-8")


def _sim3_with_identity(payload: dict) -> dict:
    if payload.get("status") != "VALIDATED":
        raise ValueError("frozen Sim(3) is not VALIDATED")
    bound = dict(payload)
    bound["wallId"] = JIULONGFENG_WALL_ID
    bound["wallBuildRunId"] = JIULONGFENG_RUN_ID
    bound["colmapModelFingerprint"] = JIULONGFENG_FINGERPRINT
    bound["modelFingerprint"] = JIULONGFENG_FINGERPRINT
    return bound


def _production_ingested_route(payload: dict) -> dict:
    if payload.get("routeId") != "route_test_01":
        raise ValueError("expected frozen route_test_01 geometry")
    if payload.get("polylineSha256") != FROZEN_POLYLINE_SHA256:
        raise ValueError("frozen polyline hash mismatch")
    ingested = dict(payload)
    ingested["routeId"] = PRODUCTION_ROUTE_ID
    ingested["routeName"] = PRODUCTION_ROUTE_NAME
    ingested["grade"] = "unspecified"
    ingested["quickdraws"] = "unspecified"
    ingested["boltCount"] = 0
    ingested["anchorCount"] = 0
    ingested["wallBuildRunId"] = JIULONGFENG_RUN_ID
    ingested["colmapModelFingerprint"] = JIULONGFENG_FINGERPRINT
    ingested["productionRoutePackage"] = "CREATED"
    return ingested


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
