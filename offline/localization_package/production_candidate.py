"""Build the unpublished Jinshidong production release candidate r000001.

Does not publish. Does not promote. Does not write COS.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from offline.catalog_promotion.location import JINSHIDONG_CATALOG_LOCATION, JINSHIDONG_DISPLAY_NAME
from offline.localization_package.cloud_manifest import local_cloud_manifest
from offline.localization_package.layout import asset_path, cloud_manifest_path, evidence_path, package_json_path
from offline.localization_package.schema import (
    ENVIRONMENT_PRODUCTION,
    STATE_PACKAGE_READY,
    TYPE_S_WALL_COLMAP,
)
from offline.localization_package.validate import validate_package_dir
from offline.route_ingestion.production_asset import (
    ASSET_ID as ROUTES_ASSET_ID,
    TYPE_WALL_ROUTES,
    build_production_route_asset,
)

JINSHIDONG_WALL_ID = "wall_jinshidong_01"
JINSHIDONG_RUN_ID = "wb_20260906T024519Z_6e08b5ff"
JINSHIDONG_FINGERPRINT = "32e9791497d9c9584acf455dc0942762f1d3e1993e9b4e682723408c1294350c"
PRODUCTION_RELEASE_ID = "r000001"
SOURCE_RELEASE_ID = "r000000"


def frozen_localization_package(root: Path) -> Path:
    return (
        root
        / "offline"
        / "work"
        / JINSHIDONG_WALL_ID
        / "wall_build"
        / JINSHIDONG_RUN_ID
        / "localization_package"
    )


def frozen_ingested_dir(root: Path) -> Path:
    return (
        root
        / "offline"
        / "work"
        / JINSHIDONG_WALL_ID
        / "route_ingestion"
        / f"bound_{JINSHIDONG_RUN_ID}"
        / "ingested"
    )


def production_candidate_dir(root: Path) -> Path:
    return root / "offline" / "packages" / JINSHIDONG_WALL_ID / PRODUCTION_RELEASE_ID


def load_ingested_routes(ingested_dir: Path) -> list[dict]:
    from offline.route_ingestion.production_asset import EXPECTED_JINSHIDONG_ROUTE_IDS

    records = []
    for route_id in EXPECTED_JINSHIDONG_ROUTE_IDS:
        path = ingested_dir / f"{route_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"missing ingested route {path}")
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def build_jinshidong_production_candidate(
    root: Path,
    *,
    dest: Path | None = None,
    created_at: str | None = None,
) -> dict:
    source = frozen_localization_package(root)
    if not source.is_dir():
        raise FileNotFoundError(f"missing frozen localization package {source}")
    source_package = json.loads(package_json_path(source).read_text(encoding="utf-8"))
    if source_package.get("wallId") != JINSHIDONG_WALL_ID:
        raise ValueError("frozen package wallId mismatch")
    if source_package.get("sourceBuild", {}).get("runId") != JINSHIDONG_RUN_ID:
        raise ValueError("frozen package runId mismatch")
    declared_fp = (source_package.get("sourceBuild") or {}).get("colmapSourceIdentity") or {}
    if declared_fp.get("modelFingerprint") != JINSHIDONG_FINGERPRINT:
        raise ValueError("frozen package fingerprint mismatch")

    ingested = load_ingested_routes(frozen_ingested_dir(root))
    routes_payload = build_production_route_asset(
        wall_id=JINSHIDONG_WALL_ID,
        release_id=PRODUCTION_RELEASE_ID,
        run_id=JINSHIDONG_RUN_ID,
        model_fingerprint=JINSHIDONG_FINGERPRINT,
        ingested_records=ingested,
    )
    routes_bytes = (json.dumps(routes_payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    routes_spec = {
        "assetId": ROUTES_ASSET_ID,
        "type": TYPE_WALL_ROUTES,
        "sha256": _sha(routes_bytes),
        "bytes": len(routes_bytes),
        "present": True,
        "authorized": True,
    }

    dest_root = dest if dest is not None else production_candidate_dir(root)
    dest_root.mkdir(parents=True, exist_ok=True)
    (dest_root / "assets").mkdir(parents=True, exist_ok=True)
    (dest_root / "evidence").mkdir(parents=True, exist_ok=True)

    for name in ("stage3-descriptors", "stage3-landmarks", "s-wall-colmap"):
        shutil.copy2(asset_path(source, name), asset_path(dest_root, name))
    asset_path(dest_root, ROUTES_ASSET_ID).write_bytes(routes_bytes)
    for name in (
        "stage2_input_selection.json",
        "positioning_quality.json",
        "height_vertical_datum.json",
        "colmap_source_identity.json",
        "freeze.json",
    ):
        shutil.copy2(evidence_path(source, name), evidence_path(dest_root, name))

    package = dict(source_package)
    package["releaseId"] = PRODUCTION_RELEASE_ID
    package["environment"] = ENVIRONMENT_PRODUCTION
    package["packageState"] = STATE_PACKAGE_READY
    package["capabilities"] = {"localizationReady": True, "routeArReady": False}
    package["routes"] = routes_spec
    package["catalogLocation"] = dict(JINSHIDONG_CATALOG_LOCATION)
    package["displayName"] = JINSHIDONG_DISPLAY_NAME
    package["notACatalogRelease"] = True
    package.pop("notAProductionRelease", None)

    created = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    metric = dict(package["metricTransform"])
    manifest = local_cloud_manifest(
        wall_id=JINSHIDONG_WALL_ID,
        release_id=PRODUCTION_RELEASE_ID,
        created_at=created,
        descriptors=package["stage3"]["descriptors"],
        landmarks=package["stage3"]["landmarks"],
        metric=metric,
        routes=routes_spec,
    )
    package_json_path(dest_root).write_text(json.dumps(package, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cloud_manifest_path(dest_root).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    result = validate_package_dir(dest_root)
    if not result.ok or result.package_state != STATE_PACKAGE_READY or not result.localization_ready:
        raise ValueError(f"production candidate is not PACKAGE_READY: {result.reason_codes}")
    if result.release_id != PRODUCTION_RELEASE_ID or result.wall_id != JINSHIDONG_WALL_ID:
        raise ValueError("production candidate identity mismatch")
    return {
        "packageDir": str(dest_root),
        "wallId": JINSHIDONG_WALL_ID,
        "releaseId": PRODUCTION_RELEASE_ID,
        "runId": JINSHIDONG_RUN_ID,
        "colmapModelFingerprint": JINSHIDONG_FINGERPRINT,
        "displayName": JINSHIDONG_DISPLAY_NAME,
        "catalogLocation": dict(JINSHIDONG_CATALOG_LOCATION),
        "packageState": result.package_state,
        "localizationReady": result.localization_ready,
        "routeArReady": result.route_ar_ready,
        "reasonCodes": result.reason_codes,
        "metricType": TYPE_S_WALL_COLMAP,
        "routesAssetId": ROUTES_ASSET_ID,
        "published": False,
        "catalogDiscoverable": False,
        "sourceReleaseId": SOURCE_RELEASE_ID,
    }


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
