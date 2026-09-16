from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from offline.catalog_promotion.location import (
    JIULONGFENG_CATALOG_LOCATION,
    JIULONGFENG_DISPLAY_NAME,
    JIULONGFENG_SRS_ORIGIN_EASTING,
    JIULONGFENG_SRS_ORIGIN_ELLH,
    JIULONGFENG_SRS_ORIGIN_NORTHING,
    JIULONGFENG_UTM_ZONE,
    JIULONGFENG_WALL_ID,
    JINSHIDONG_CATALOG_LOCATION,
    JINSHIDONG_WALL_ID,
    select_wall_id,
)
from offline.catalog_promotion.projector import project_catalog
from offline.catalog_promotion.record import promotion_record
from offline.localization_package.jiulongfeng_production_candidate import (
    FROZEN_POLYLINE_SHA256,
    JIULONGFENG_FINGERPRINT,
    JIULONGFENG_RUN_ID,
    LIVE_PRODUCTION,
    PRODUCTION_RELEASE_ID,
    PRODUCTION_ROUTE_ID,
    PRODUCTION_ROUTE_NAME,
    build_jiulongfeng_production_candidate,
    choose_unused_production_release_id,
    frozen_colmap_dir,
    frozen_ingested_route_path,
    frozen_sim3_path,
    frozen_stage3_dir,
)
from offline.localization_package.layout import asset_path, cloud_manifest_path, package_json_path
from offline.localization_package.schema import ENVIRONMENT_PRODUCTION, STATE_PACKAGE_READY
from offline.localization_package.validate import validate_package_dir
from offline.publisher.keys import published_asset_key, published_manifest_key, published_promotion_key
from offline.qualification.geodesy import utm_to_geographic
from offline.route_ingestion.ingest import polyline_sha256
from offline.route_ingestion.production_asset import ASSET_ID as ROUTES_ASSET_ID
from offline.route_ingestion.production_asset import EXPECTED_JIULONGFENG_ROUTE_IDS, TYPE_WALL_ROUTES

ROOT = Path(__file__).resolve().parents[2]


class JiulongfengProductionCandidateTests(unittest.TestCase):
    def test_catalog_location_is_recomputed_from_verified_srs_origin(self) -> None:
        lat, lon = utm_to_geographic(
            JIULONGFENG_SRS_ORIGIN_EASTING,
            JIULONGFENG_SRS_ORIGIN_NORTHING,
            JIULONGFENG_UTM_ZONE,
            True,
        )
        sim3 = json.loads(frozen_sim3_path(ROOT).read_text(encoding="utf-8"))
        origin = sim3["wallLocalOrigin"]["values"]
        self.assertEqual(origin[0], JIULONGFENG_SRS_ORIGIN_EASTING)
        self.assertEqual(origin[1], JIULONGFENG_SRS_ORIGIN_NORTHING)
        self.assertEqual(origin[2], JIULONGFENG_SRS_ORIGIN_ELLH)
        self.assertEqual(lat, JIULONGFENG_CATALOG_LOCATION["latitudeDeg"])
        self.assertEqual(lon, JIULONGFENG_CATALOG_LOCATION["longitudeDeg"])
        self.assertEqual(origin[2], JIULONGFENG_CATALOG_LOCATION["altitudeMeters"])
        self.assertEqual(JIULONGFENG_CATALOG_LOCATION["purpose"], "wall_candidate_selection_only")
        self.assertNotEqual(
            round(lat, 6),
            JIULONGFENG_CATALOG_LOCATION["latitudeDeg"],
        )

    def test_first_unused_production_release_id_is_r000001_when_absent_live(self) -> None:
        chosen = choose_unused_production_release_id(ROOT, live_host=None)
        self.assertEqual(chosen, PRODUCTION_RELEASE_ID)
        self.assertEqual(PRODUCTION_RELEASE_ID, "r000001")

    def test_candidate_matches_validator_manifest_and_hashes(self) -> None:
        if not frozen_stage3_dir(ROOT).is_dir():
            self.skipTest("frozen Jiulongfeng Stage 3 not present")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / PRODUCTION_RELEASE_ID
            summary = build_jiulongfeng_production_candidate(
                ROOT, dest=dest, created_at="2026-09-15T06:00:00Z", release_id=PRODUCTION_RELEASE_ID
            )
            result = validate_package_dir(dest)
            self.assertTrue(result.ok)
            self.assertEqual(result.package_state, STATE_PACKAGE_READY)
            self.assertTrue(result.localization_ready)
            self.assertFalse(result.route_ar_ready)
            self.assertEqual(result.reason_codes, [])
            package = json.loads(package_json_path(dest).read_text(encoding="utf-8"))
            self.assertEqual(package["wallId"], JIULONGFENG_WALL_ID)
            self.assertEqual(package["releaseId"], PRODUCTION_RELEASE_ID)
            self.assertEqual(package["packageState"], STATE_PACKAGE_READY)
            self.assertEqual(package["environment"], ENVIRONMENT_PRODUCTION)
            self.assertTrue(package["capabilities"]["localizationReady"])
            self.assertFalse(package["capabilities"]["routeArReady"])
            self.assertEqual(package["sourceBuild"]["runId"], JIULONGFENG_RUN_ID)
            self.assertEqual(
                package["sourceBuild"]["colmapSourceIdentity"]["modelFingerprint"],
                JIULONGFENG_FINGERPRINT,
            )
            self.assertEqual(package["catalogLocation"], JIULONGFENG_CATALOG_LOCATION)
            self.assertEqual(package["displayName"], JIULONGFENG_DISPLAY_NAME)
            self.assertTrue(package["routes"]["present"])
            self.assertEqual(package["routes"]["type"], TYPE_WALL_ROUTES)
            identity = json.loads((dest / "evidence" / "colmap_source_identity.json").read_text(encoding="utf-8"))
            self.assertEqual(identity["wallId"], JIULONGFENG_WALL_ID)
            self.assertEqual(identity["modelFingerprint"], JIULONGFENG_FINGERPRINT)
            self.assertEqual(identity["colmapSourceIdentityReasonCode"], "COLMAP_SOURCE_IDENTITY_PROVEN")
            self.assertTrue(identity["colmapSourceIdentityExecutionAllowed"])
            freeze = json.loads((dest / "evidence" / "freeze.json").read_text(encoding="utf-8"))
            self.assertEqual(freeze["wallId"], JIULONGFENG_WALL_ID)
            self.assertEqual(freeze["wallBuildRunId"], JIULONGFENG_RUN_ID)
            self.assertEqual(freeze["colmapModelFingerprint"], JIULONGFENG_FINGERPRINT)
            manifest = json.loads(cloud_manifest_path(dest).read_text(encoding="utf-8"))
            self.assertEqual(manifest["releaseId"], PRODUCTION_RELEASE_ID)
            types = {item["type"] for item in manifest["assets"]}
            self.assertEqual(
                types,
                {
                    "reference_descriptors_rvs1",
                    "reference_landmarks_json",
                    "s_wall_colmap_json",
                    TYPE_WALL_ROUTES,
                },
            )
            for item in manifest["assets"]:
                path = dest / "assets" / item["assetId"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"], item["assetId"])
                self.assertEqual(path.stat().st_size, item["bytes"], item["assetId"])
            landmarks = json.loads(asset_path(dest, "stage3-landmarks").read_text(encoding="utf-8"))
            self.assertEqual(landmarks["wallId"], JIULONGFENG_WALL_ID)
            self.assertNotIn("developmentFixtureOnly", landmarks)
            self.assertNotIn("notAWallPackage", landmarks)
            sim3 = json.loads(asset_path(dest, "s-wall-colmap").read_text(encoding="utf-8"))
            self.assertEqual(sim3["status"], "VALIDATED")
            self.assertEqual(sim3["wallId"], JIULONGFENG_WALL_ID)
            self.assertEqual(sim3["wallBuildRunId"], JIULONGFENG_RUN_ID)
            self.assertEqual(sim3["colmapModelFingerprint"], JIULONGFENG_FINGERPRINT)
            self.assertEqual(sim3["scale"], 3.19764417024824)
            routes = json.loads(asset_path(dest, ROUTES_ASSET_ID).read_text(encoding="utf-8"))
            self.assertEqual([row["routeId"] for row in routes["routes"]], list(EXPECTED_JIULONGFENG_ROUTE_IDS))
            self.assertEqual(routes["routes"][0]["routeName"], PRODUCTION_ROUTE_NAME)
            self.assertEqual(routes["routes"][0]["polylineSha256"], FROZEN_POLYLINE_SHA256)
            self.assertNotEqual(routes["routes"][0]["routeId"], "route_test_01")
            self.assertEqual(summary["releaseId"], PRODUCTION_RELEASE_ID)
            self.assertFalse(summary["published"])
            self.assertFalse(summary["catalogDiscoverable"])

    def test_production_route_keeps_frozen_polyline_vertices(self) -> None:
        if not frozen_ingested_route_path(ROOT).is_file():
            self.skipTest("frozen Gate 5A route not present")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / PRODUCTION_RELEASE_ID
            build_jiulongfeng_production_candidate(
                ROOT, dest=dest, created_at="2026-09-15T06:00:00Z", release_id=PRODUCTION_RELEASE_ID
            )
            frozen = json.loads(frozen_ingested_route_path(ROOT).read_text(encoding="utf-8"))
            routes = json.loads(asset_path(dest, ROUTES_ASSET_ID).read_text(encoding="utf-8"))
            runtime = routes["routes"][0]
            self.assertEqual(runtime["polyline"], frozen["polyline"])
            self.assertEqual(polyline_sha256(runtime["polyline"]), FROZEN_POLYLINE_SHA256)
            self.assertEqual(runtime["polylineSha256"], frozen["polylineSha256"])
            self.assertEqual(runtime["routeId"], PRODUCTION_ROUTE_ID)
            self.assertEqual(runtime["routeName"], PRODUCTION_ROUTE_NAME)

    def test_gps_to_runtime_ready_uses_candidate_not_live_cloud(self) -> None:
        if not frozen_stage3_dir(ROOT).is_dir():
            self.skipTest("frozen Jiulongfeng Stage 3 not present")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / PRODUCTION_RELEASE_ID
            build_jiulongfeng_production_candidate(
                ROOT, dest=dest, created_at="2026-09-15T06:00:00Z", release_id=PRODUCTION_RELEASE_ID
            )
            projected = project_catalog(
                [
                    promotion_record(
                        wall_id=JINSHIDONG_WALL_ID,
                        release_id="r000001",
                        name="金狮洞",
                        promoted_at="2026-09-09T06:00:00Z",
                        release_manifest_sha256="b" * 64,
                        environment=ENVIRONMENT_PRODUCTION,
                        catalog_location=JINSHIDONG_CATALOG_LOCATION,
                    ),
                    promotion_record(
                        wall_id=JIULONGFENG_WALL_ID,
                        release_id=PRODUCTION_RELEASE_ID,
                        name=JIULONGFENG_DISPLAY_NAME,
                        promoted_at="2026-09-15T06:00:00Z",
                        release_manifest_sha256="c" * 64,
                        environment=ENVIRONMENT_PRODUCTION,
                        catalog_location=JIULONGFENG_CATALOG_LOCATION,
                    ),
                ]
            )
            loc = JIULONGFENG_CATALOG_LOCATION
            wall_id = select_wall_id(
                latitude_deg=loc["latitudeDeg"],
                longitude_deg=loc["longitudeDeg"],
                walls=projected["walls"],
            )
            self.assertEqual(wall_id, JIULONGFENG_WALL_ID)
            jinshidong = select_wall_id(
                latitude_deg=JINSHIDONG_CATALOG_LOCATION["latitudeDeg"],
                longitude_deg=JINSHIDONG_CATALOG_LOCATION["longitudeDeg"],
                walls=projected["walls"],
            )
            self.assertEqual(jinshidong, JINSHIDONG_WALL_ID)
            entry = next(item for item in projected["walls"] if item["wallId"] == JIULONGFENG_WALL_ID)
            self.assertEqual(entry["latestReleaseId"], PRODUCTION_RELEASE_ID)
            result = validate_package_dir(dest)
            self.assertTrue(result.ok)
            self.assertTrue(result.localization_ready)
            manifest = json.loads(cloud_manifest_path(dest).read_text(encoding="utf-8"))
            assets = {item["assetId"]: item for item in manifest["assets"]}
            for asset_id, spec in assets.items():
                path = dest / "assets" / asset_id
                self.assertTrue(path.is_file(), asset_id)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(digest, spec["sha256"], asset_id)
                self.assertEqual(path.stat().st_size, spec["bytes"], asset_id)
            sim3 = json.loads((dest / "assets" / "s-wall-colmap").read_text(encoding="utf-8"))
            self.assertEqual(sim3["status"], "VALIDATED")
            self.assertEqual(sim3["scale"], 3.19764417024824)
            routes = json.loads((dest / "assets" / "wall-routes").read_text(encoding="utf-8"))
            self.assertEqual(routes["routes"][0]["routeId"], PRODUCTION_ROUTE_ID)
            self.assertEqual(routes["routes"][0]["routeName"], PRODUCTION_ROUTE_NAME)
            self.assertEqual(routes["releaseId"], PRODUCTION_RELEASE_ID)
            self.assertEqual(routes["coordinateFrame"], "WallMetricMeters")
            descriptors = dest / "assets" / "stage3-descriptors"
            self.assertEqual(descriptors.read_bytes()[:4], b"RVS1")
            landmarks = json.loads((dest / "assets" / "stage3-landmarks").read_text(encoding="utf-8"))
            self.assertEqual(landmarks["wallId"], JIULONGFENG_WALL_ID)

    def test_publish_would_write_four_assets_and_one_promotion_record(self) -> None:
        keys = [
            published_asset_key(JIULONGFENG_WALL_ID, PRODUCTION_RELEASE_ID, "stage3-descriptors"),
            published_asset_key(JIULONGFENG_WALL_ID, PRODUCTION_RELEASE_ID, "stage3-landmarks"),
            published_asset_key(JIULONGFENG_WALL_ID, PRODUCTION_RELEASE_ID, "s-wall-colmap"),
            published_asset_key(JIULONGFENG_WALL_ID, PRODUCTION_RELEASE_ID, ROUTES_ASSET_ID),
            published_manifest_key(JIULONGFENG_WALL_ID, PRODUCTION_RELEASE_ID),
        ]
        self.assertEqual(keys[-1], "published/wall_jiulongfeng_01/r000001/manifest.json")
        self.assertEqual(
            published_promotion_key(JIULONGFENG_WALL_ID, PRODUCTION_RELEASE_ID),
            "published/promotions/wall_jiulongfeng_01/r000001.json",
        )
        self.assertNotIn("published/catalog.json", keys)

    def test_on_disk_candidate_matches_unpublished_contract(self) -> None:
        dest = ROOT / "offline" / "packages" / JIULONGFENG_WALL_ID / PRODUCTION_RELEASE_ID
        package_path = package_json_path(dest)
        if not package_path.is_file():
            self.skipTest("on-disk Jiulongfeng production candidate not present")
        package = json.loads(package_path.read_text(encoding="utf-8"))
        self.assertEqual(package["wallId"], JIULONGFENG_WALL_ID)
        self.assertEqual(package["releaseId"], PRODUCTION_RELEASE_ID)
        self.assertEqual(package["packageState"], STATE_PACKAGE_READY)
        self.assertEqual(package["environment"], ENVIRONMENT_PRODUCTION)
        self.assertTrue(package["capabilities"]["localizationReady"])
        self.assertFalse(package["capabilities"]["routeArReady"])
        self.assertEqual(package["sourceBuild"]["runId"], JIULONGFENG_RUN_ID)
        self.assertEqual(
            package["sourceBuild"]["colmapSourceIdentity"]["modelFingerprint"],
            JIULONGFENG_FINGERPRINT,
        )
        self.assertEqual(package["catalogLocation"], JIULONGFENG_CATALOG_LOCATION)
        self.assertTrue(package["notACatalogRelease"])
        manifest = json.loads(cloud_manifest_path(dest).read_text(encoding="utf-8"))
        self.assertEqual(manifest["releaseId"], PRODUCTION_RELEASE_ID)
        for item in manifest["assets"]:
            path = dest / "assets" / item["assetId"]
            if not path.is_file():
                self.skipTest(f"candidate asset {item['assetId']} not present locally")
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
            self.assertEqual(path.stat().st_size, item["bytes"])
        result = validate_package_dir(dest)
        self.assertTrue(result.ok)
        self.assertEqual(result.package_state, STATE_PACKAGE_READY)
        self.assertTrue(result.localization_ready)
        self.assertFalse(result.route_ar_ready)

    def test_live_production_catalog_can_select_jiulongfeng(self) -> None:
        try:
            with urllib.request.urlopen(f"{LIVE_PRODUCTION}/v1/walls", timeout=10) as response:
                production = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            self.skipTest("live production HTTPS catalog not reachable")
        entry = next((item for item in production.get("walls", []) if item.get("wallId") == JIULONGFENG_WALL_ID), None)
        if entry is None:
            self.skipTest("Jiulongfeng not yet in live production catalog")
        self.assertEqual(entry["name"], JIULONGFENG_DISPLAY_NAME)
        self.assertEqual(entry["latestReleaseId"], PRODUCTION_RELEASE_ID)
        self.assertEqual(entry["catalogLocation"], JIULONGFENG_CATALOG_LOCATION)
        chosen = select_wall_id(
            latitude_deg=JIULONGFENG_CATALOG_LOCATION["latitudeDeg"],
            longitude_deg=JIULONGFENG_CATALOG_LOCATION["longitudeDeg"],
            walls=production.get("walls", []),
        )
        self.assertEqual(chosen, JIULONGFENG_WALL_ID)

    def test_frozen_colmap_is_the_47_image_export(self) -> None:
        colmap = frozen_colmap_dir(ROOT)
        if not colmap.is_dir():
            self.skipTest("frozen Jiulongfeng COLMAP not present")
        manifest = json.loads((colmap / "colmap_source_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["imageCount"], 47)
        self.assertEqual(len(manifest["images"]), 47)


class JiulongfengLiveRuntimeDiscoveryTests(unittest.TestCase):
    def test_live_https_assets_hashes_sim3_and_white_wall_route(self) -> None:
        try:
            with urllib.request.urlopen(f"{LIVE_PRODUCTION}/v1/walls", timeout=10) as response:
                production = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            self.skipTest("live production HTTPS catalog not reachable")
        entry = next((item for item in production.get("walls", []) if item.get("wallId") == JIULONGFENG_WALL_ID), None)
        if entry is None:
            self.skipTest("Jiulongfeng not yet in live production catalog")
        release_id = entry["latestReleaseId"]
        loc = JIULONGFENG_CATALOG_LOCATION
        self.assertEqual(
            select_wall_id(latitude_deg=loc["latitudeDeg"], longitude_deg=loc["longitudeDeg"], walls=production["walls"]),
            JIULONGFENG_WALL_ID,
        )
        convenience = _get_json(f"{LIVE_PRODUCTION}/v1/walls/{JIULONGFENG_WALL_ID}/manifest")
        exact = _get_json(f"{LIVE_PRODUCTION}/v1/walls/{JIULONGFENG_WALL_ID}/releases/{release_id}/manifest")
        self.assertEqual(convenience, exact)
        self.assertEqual(exact["wallId"], JIULONGFENG_WALL_ID)
        self.assertEqual(exact["releaseId"], release_id)
        downloaded = {}
        for item in exact["assets"]:
            url = f"{LIVE_PRODUCTION}/v1/walls/{JIULONGFENG_WALL_ID}/releases/{release_id}/assets/{item['assetId']}"
            data = _get_bytes(url)
            self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"], item["assetId"])
            self.assertEqual(len(data), item["bytes"], item["assetId"])
            downloaded[item["assetId"]] = data
        sim3 = json.loads(downloaded["s-wall-colmap"].decode("utf-8"))
        self.assertEqual(sim3["status"], "VALIDATED")
        self.assertEqual(sim3["scale"], 3.19764417024824)
        self.assertEqual(sim3["wallId"], JIULONGFENG_WALL_ID)
        routes = json.loads(downloaded["wall-routes"].decode("utf-8"))
        self.assertEqual(routes["schema"], "cragpal.wall-routes.v1")
        self.assertEqual(routes["routes"][0]["routeId"], PRODUCTION_ROUTE_ID)
        self.assertEqual(routes["routes"][0]["routeName"], PRODUCTION_ROUTE_NAME)
        self.assertEqual(routes["routes"][0]["polylineSha256"], FROZEN_POLYLINE_SHA256)
        self.assertEqual(downloaded["stage3-descriptors"][:4], b"RVS1")
        landmarks = json.loads(downloaded["stage3-landmarks"].decode("utf-8"))
        self.assertEqual(landmarks["wallId"], JIULONGFENG_WALL_ID)
        self.assertNotIn("developmentFixtureOnly", landmarks)
        self.assertNotIn("notAWallPackage", landmarks)


def _get_json(url: str) -> dict:
    return json.loads(_get_bytes(url).decode("utf-8"))


def _get_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()
