from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from offline.catalog_promotion.location import JINSHIDONG_CATALOG_LOCATION, JINSHIDONG_WALL_ID, select_wall_id
from offline.catalog_promotion.record import promotion_record
from offline.catalog_promotion.projector import project_catalog
from offline.localization_package.layout import asset_path, cloud_manifest_path, package_json_path
from offline.localization_package.production_candidate import (
    JINSHIDONG_FINGERPRINT,
    JINSHIDONG_RUN_ID,
    PRODUCTION_RELEASE_ID,
    build_jinshidong_production_candidate,
    frozen_localization_package,
)
from offline.localization_package.schema import ENVIRONMENT_PRODUCTION, STATE_PACKAGE_READY
from offline.localization_package.validate import validate_package_dir
from offline.publisher.keys import published_asset_key, published_manifest_key, published_promotion_key
from offline.route_ingestion.production_asset import ASSET_ID as ROUTES_ASSET_ID
from offline.route_ingestion.production_asset import EXPECTED_JINSHIDONG_ROUTE_IDS, TYPE_WALL_ROUTES

ROOT = Path(__file__).resolve().parents[2]
LIVE = "http://124.223.178.91"


class JinshidongProductionCandidateTests(unittest.TestCase):
    def test_r000001_is_the_first_unpublished_production_release_id(self) -> None:
        self.assertEqual(PRODUCTION_RELEASE_ID, "r000001")
        self.assertNotEqual(PRODUCTION_RELEASE_ID, "r000000")

    def test_candidate_matches_validator_manifest_and_hashes(self) -> None:
        source = frozen_localization_package(ROOT)
        if not source.is_dir():
            self.skipTest("frozen Jinshidong localization package not present")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "r000001"
            summary = build_jinshidong_production_candidate(ROOT, dest=dest, created_at="2026-09-09T06:00:00Z")
            result = validate_package_dir(dest)
            self.assertTrue(result.ok)
            self.assertEqual(result.package_state, STATE_PACKAGE_READY)
            self.assertTrue(result.localization_ready)
            self.assertFalse(result.route_ar_ready)
            self.assertEqual(result.reason_codes, [])
            package = json.loads(package_json_path(dest).read_text(encoding="utf-8"))
            self.assertEqual(package["releaseId"], PRODUCTION_RELEASE_ID)
            self.assertEqual(package["packageState"], STATE_PACKAGE_READY)
            self.assertTrue(package["capabilities"]["localizationReady"])
            self.assertFalse(package["capabilities"]["routeArReady"])
            self.assertEqual(package["sourceBuild"]["runId"], JINSHIDONG_RUN_ID)
            self.assertEqual(package["sourceBuild"]["colmapSourceIdentity"]["modelFingerprint"], JINSHIDONG_FINGERPRINT)
            self.assertEqual(package["catalogLocation"], JINSHIDONG_CATALOG_LOCATION)
            self.assertTrue(package["routes"]["present"])
            self.assertEqual(package["routes"]["type"], TYPE_WALL_ROUTES)
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
            routes = json.loads(asset_path(dest, ROUTES_ASSET_ID).read_text(encoding="utf-8"))
            self.assertEqual([row["routeId"] for row in routes["routes"]], list(EXPECTED_JINSHIDONG_ROUTE_IDS))
            self.assertEqual(summary["releaseId"], PRODUCTION_RELEASE_ID)
            self.assertFalse(summary["published"])
            self.assertFalse(summary["catalogDiscoverable"])

    def test_gps_to_runtime_ready_uses_candidate_not_live_cloud(self) -> None:
        source = frozen_localization_package(ROOT)
        if not source.is_dir():
            self.skipTest("frozen Jinshidong localization package not present")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "r000001"
            build_jinshidong_production_candidate(ROOT, dest=dest, created_at="2026-09-09T06:00:00Z")
            projected = project_catalog(
                [
                    promotion_record(
                        wall_id=JINSHIDONG_WALL_ID,
                        release_id=PRODUCTION_RELEASE_ID,
                        name="金狮洞",
                        promoted_at="2026-09-09T06:00:00Z",
                        release_manifest_sha256="b" * 64,
                        environment=ENVIRONMENT_PRODUCTION,
                        catalog_location=JINSHIDONG_CATALOG_LOCATION,
                    )
                ]
            )
            loc = JINSHIDONG_CATALOG_LOCATION
            wall_id = select_wall_id(
                latitude_deg=loc["latitudeDeg"],
                longitude_deg=loc["longitudeDeg"],
                walls=projected["walls"],
            )
            self.assertEqual(wall_id, JINSHIDONG_WALL_ID)
            self.assertEqual(projected["walls"][0]["latestReleaseId"], PRODUCTION_RELEASE_ID)
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
            self.assertAlmostEqual(sim3["scale"], 3.7780058545133315)
            routes = json.loads((dest / "assets" / "wall-routes").read_text(encoding="utf-8"))
            self.assertEqual([row["routeId"] for row in routes["routes"]], list(EXPECTED_JINSHIDONG_ROUTE_IDS))
            self.assertEqual(routes["releaseId"], PRODUCTION_RELEASE_ID)
            self.assertEqual(routes["coordinateFrame"], "WallMetricMeters")

    def test_live_cloud_does_not_yet_contain_jinshidong(self) -> None:
        try:
            with urllib.request.urlopen(f"{LIVE}/v1/walls", timeout=10) as response:
                production = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{LIVE}/v1/debug/walls", timeout=10) as response:
                debug = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            self.skipTest("live cloud catalog not reachable")
        prod_ids = {item["wallId"] for item in production.get("walls", [])}
        debug_ids = {item["wallId"] for item in debug.get("walls", [])}
        self.assertNotIn(JINSHIDONG_WALL_ID, prod_ids)
        self.assertNotIn(JINSHIDONG_WALL_ID, debug_ids)
        try:
            urllib.request.urlopen(
                f"{LIVE}/v1/walls/{JINSHIDONG_WALL_ID}/releases/{PRODUCTION_RELEASE_ID}/manifest",
                timeout=10,
            )
            self.fail("live exact Jinshidong r000001 should be 404 until publish")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)

    def test_publish_would_write_four_assets_and_one_promotion_record(self) -> None:
        keys = [
            published_asset_key(JINSHIDONG_WALL_ID, PRODUCTION_RELEASE_ID, "stage3-descriptors"),
            published_asset_key(JINSHIDONG_WALL_ID, PRODUCTION_RELEASE_ID, "stage3-landmarks"),
            published_asset_key(JINSHIDONG_WALL_ID, PRODUCTION_RELEASE_ID, "s-wall-colmap"),
            published_asset_key(JINSHIDONG_WALL_ID, PRODUCTION_RELEASE_ID, ROUTES_ASSET_ID),
            published_manifest_key(JINSHIDONG_WALL_ID, PRODUCTION_RELEASE_ID),
        ]
        self.assertEqual(
            keys[-1],
            "published/wall_jinshidong_01/r000001/manifest.json",
        )
        self.assertEqual(
            published_promotion_key(JINSHIDONG_WALL_ID, PRODUCTION_RELEASE_ID),
            "published/promotions/wall_jinshidong_01/r000001.json",
        )
        self.assertNotIn("published/catalog.json", keys)

    def test_on_disk_candidate_matches_unpublished_r000001_contract(self) -> None:
        dest = ROOT / "offline" / "packages" / JINSHIDONG_WALL_ID / PRODUCTION_RELEASE_ID
        package_path = package_json_path(dest)
        if not package_path.is_file():
            self.skipTest("on-disk production candidate not present")
        package = json.loads(package_path.read_text(encoding="utf-8"))
        self.assertEqual(package["wallId"], JINSHIDONG_WALL_ID)
        self.assertEqual(package["releaseId"], PRODUCTION_RELEASE_ID)
        self.assertEqual(package["packageState"], STATE_PACKAGE_READY)
        self.assertEqual(package["environment"], ENVIRONMENT_PRODUCTION)
        self.assertTrue(package["capabilities"]["localizationReady"])
        self.assertFalse(package["capabilities"]["routeArReady"])
        self.assertEqual(package["sourceBuild"]["runId"], JINSHIDONG_RUN_ID)
        self.assertEqual(
            package["sourceBuild"]["colmapSourceIdentity"]["modelFingerprint"],
            JINSHIDONG_FINGERPRINT,
        )
        self.assertEqual(package["catalogLocation"], JINSHIDONG_CATALOG_LOCATION)
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
