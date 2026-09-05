"""Classified catalog audiences. Fake/local only. No COS writes."""

from __future__ import annotations

import ast
import inspect
import json
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.catalog_projection import (
    ProjectionError,
    filter_catalog_for_audience,
    merge_legacy_and_projected,
    project_promotions,
)
from app.contract import (
    AUDIENCE_DEBUG_TEST,
    AUDIENCE_PRODUCTION,
    CATALOG_SCHEMA,
    ENVIRONMENT_DEVELOPMENT_TEST,
    ENVIRONMENT_PRODUCTION,
    ContractError,
    classified_environment_from_payload,
    empty_catalog,
    validate_catalog,
)
from app.main import create_app
from app.memory_store import (
    EXAMPLE_ASSET_BYTES,
    EXAMPLE_ASSET_ID,
    EXAMPLE_RELEASE_ID,
    EXAMPLE_WALL_ID,
    MemoryStore,
    example_catalog,
    example_manifest,
)
from app.promotion import (
    PromotionRecordError,
    decode_promotion_record,
    promotion_identity,
    promotion_record,
)

from tests.test_api import _client, _explicit_manifest_path

PROD_WALL = "wall_classified_prod_01"
DEV_WALL = "wall_classified_dev_01"
DEV_ONLY = "wall_dev_only_01"
SYNTHETIC_WALL = "wall_publisher_e2e_01"
WHEN = "2026-09-05T00:00:00Z"
SHA = "a" * 64


def _record(*, wall_id: str, release_id: str = "r000001", name: str, environment: str | None = None) -> dict:
    return promotion_record(
        wall_id=wall_id,
        release_id=release_id,
        name=name,
        promoted_at=WHEN,
        release_manifest_sha256=SHA,
        environment=environment,
    )


def _manifest(wall_id: str, release_id: str = "r000001") -> dict:
    payload = example_manifest(release_id=release_id)
    payload["wallId"] = wall_id
    payload["releaseId"] = release_id
    return payload


def _store_with(*records: dict, legacy: dict | None = None) -> MemoryStore:
    manifests = {}
    for record in records:
        manifests[(record["wallId"], record["releaseId"])] = _manifest(record["wallId"], record["releaseId"])
    if legacy:
        for item in legacy["walls"]:
            manifests[(item["wallId"], item["latestReleaseId"])] = _manifest(
                item["wallId"], item["latestReleaseId"]
            )
    return MemoryStore(
        catalog=legacy or empty_catalog(),
        manifests=manifests,
        assets={},
        promotions=list(records),
    )


class EnvironmentDecodeTests(unittest.TestCase):
    def test_old_promotion_v1_decodes_as_unspecified(self) -> None:
        payload = promotion_record(
            wall_id=SYNTHETIC_WALL,
            release_id="r000001",
            name="CragPal Publisher E2E Test Wall",
            promoted_at=WHEN,
            release_manifest_sha256=SHA,
        )
        self.assertNotIn("environment", payload)
        decoded = decode_promotion_record(payload)
        self.assertNotIn("environment", decoded)
        self.assertEqual(promotion_identity(decoded)[5], "")

    def test_new_promotion_production_roundtrip(self) -> None:
        payload = _record(wall_id=PROD_WALL, name="Prod", environment=ENVIRONMENT_PRODUCTION)
        decoded = decode_promotion_record(payload)
        self.assertEqual(decoded["environment"], ENVIRONMENT_PRODUCTION)
        self.assertEqual(promotion_identity(decoded)[5], ENVIRONMENT_PRODUCTION)

    def test_new_promotion_development_test_roundtrip(self) -> None:
        payload = _record(wall_id=DEV_WALL, name="Dev", environment=ENVIRONMENT_DEVELOPMENT_TEST)
        decoded = decode_promotion_record(payload)
        self.assertEqual(decoded["environment"], ENVIRONMENT_DEVELOPMENT_TEST)
        self.assertEqual(promotion_identity(decoded)[5], ENVIRONMENT_DEVELOPMENT_TEST)

    def test_environment_participates_in_new_immutable_identity(self) -> None:
        unspecified = _record(wall_id=PROD_WALL, name="Prod")
        production = _record(wall_id=PROD_WALL, name="Prod", environment=ENVIRONMENT_PRODUCTION)
        development = _record(wall_id=PROD_WALL, name="Prod", environment=ENVIRONMENT_DEVELOPMENT_TEST)
        self.assertNotEqual(promotion_identity(unspecified), promotion_identity(production))
        self.assertNotEqual(promotion_identity(production), promotion_identity(development))

    def test_unknown_environment_fails_closed(self) -> None:
        payload = _record(wall_id=PROD_WALL, name="Prod", environment=ENVIRONMENT_PRODUCTION)
        payload["environment"] = "prod"
        with self.assertRaises(PromotionRecordError) as exc:
            decode_promotion_record(payload)
        self.assertEqual(exc.exception.code, "PROMOTION_ENVIRONMENT_INVALID")
        with self.assertRaises(ContractError):
            classified_environment_from_payload({"environment": "dev"})
        with self.assertRaises(ContractError):
            validate_catalog(
                {
                    "schema": CATALOG_SCHEMA,
                    "walls": [
                        {
                            "wallId": PROD_WALL,
                            "name": "X",
                            "latestReleaseId": "r000001",
                            "environment": "test",
                        }
                    ],
                }
            )


class AudienceFilterTests(unittest.TestCase):
    def test_production_contains_explicit_production_only(self) -> None:
        merged = merge_legacy_and_projected(
            example_catalog(),
            project_promotions(
                [
                    _record(wall_id=PROD_WALL, name="Prod", environment=ENVIRONMENT_PRODUCTION),
                    _record(wall_id=DEV_WALL, name="Dev", environment=ENVIRONMENT_DEVELOPMENT_TEST),
                    _record(wall_id=SYNTHETIC_WALL, name="Synthetic"),
                ]
            ),
        )
        production = filter_catalog_for_audience(merged, AUDIENCE_PRODUCTION)
        debug = filter_catalog_for_audience(merged, AUDIENCE_DEBUG_TEST)
        self.assertEqual([item["wallId"] for item in production["walls"]], [PROD_WALL])
        self.assertEqual(production["walls"][0]["environment"], ENVIRONMENT_PRODUCTION)
        self.assertEqual(
            [item["wallId"] for item in debug["walls"]],
            [DEV_WALL, PROD_WALL, EXAMPLE_WALL_ID, SYNTHETIC_WALL],
        )

    def test_same_wall_conflicting_environments_fail_closed(self) -> None:
        with self.assertRaises(ProjectionError) as exc:
            project_promotions(
                [
                    _record(
                        wall_id=PROD_WALL,
                        release_id="r000001",
                        name="Prod",
                        environment=ENVIRONMENT_PRODUCTION,
                    ),
                    _record(
                        wall_id=PROD_WALL,
                        release_id="r000002",
                        name="Prod",
                        environment=ENVIRONMENT_DEVELOPMENT_TEST,
                    ),
                ]
            )
        self.assertEqual(exc.exception.code, "PROMOTION_ENVIRONMENT_CONFLICT")

    def test_highest_ordinal_cannot_cross_environment_boundary(self) -> None:
        with self.assertRaises(ProjectionError) as exc:
            project_promotions(
                [
                    _record(
                        wall_id=PROD_WALL,
                        release_id="r000001",
                        name="Prod",
                        environment=ENVIRONMENT_DEVELOPMENT_TEST,
                    ),
                    _record(
                        wall_id=PROD_WALL,
                        release_id="r000099",
                        name="Prod",
                        environment=ENVIRONMENT_PRODUCTION,
                    ),
                ]
            )
        self.assertEqual(exc.exception.code, "PROMOTION_ENVIRONMENT_CONFLICT")

    def test_unspecified_and_production_same_wall_fail_closed(self) -> None:
        with self.assertRaises(ProjectionError) as exc:
            merge_legacy_and_projected(
                {
                    "schema": CATALOG_SCHEMA,
                    "walls": [
                        {"wallId": PROD_WALL, "name": "Prod", "latestReleaseId": "r000001"}
                    ],
                },
                project_promotions(
                    [_record(wall_id=PROD_WALL, name="Prod", environment=ENVIRONMENT_PRODUCTION)]
                ),
            )
        self.assertEqual(exc.exception.code, "PROMOTION_ENVIRONMENT_CONFLICT")

    def test_no_wall_id_suffix_or_display_name_inference(self) -> None:
        source = Path(inspect.getsourcefile(filter_catalog_for_audience)).read_text(encoding="utf-8")
        start = source.index("def filter_catalog_for_audience")
        body = source[start : source.index("\ndef _entry_environment")]
        self.assertNotIn("_dev", body)
        self.assertNotIn("hasSuffix", body)
        self.assertNotIn("Jiulongfeng", body)
        self.assertNotIn("display", body.lower())
        pretty_dev = _record(
            wall_id="wall_pretty_dev",
            name="Production Wall",
            environment=ENVIRONMENT_DEVELOPMENT_TEST,
        )
        live = _record(
            wall_id="wall_live_01",
            name="Development Fixture",
            environment=ENVIRONMENT_PRODUCTION,
        )
        production = filter_catalog_for_audience(
            project_promotions([pretty_dev, live]),
            AUDIENCE_PRODUCTION,
        )
        self.assertEqual([item["wallId"] for item in production["walls"]], ["wall_live_01"])


class AudienceEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _store_with(
            _record(wall_id=PROD_WALL, name="Prod", environment=ENVIRONMENT_PRODUCTION),
            _record(wall_id=DEV_ONLY, name="Dev Only", environment=ENVIRONMENT_DEVELOPMENT_TEST),
            _record(wall_id=SYNTHETIC_WALL, name="Synthetic"),
            legacy=example_catalog(),
        )
        self.client = _client(self.store)

    def test_production_catalog_matrix(self) -> None:
        walls = {item["wallId"]: item for item in self.client.get("/v1/walls").json()["walls"]}
        self.assertIn(PROD_WALL, walls)
        self.assertEqual(walls[PROD_WALL]["environment"], ENVIRONMENT_PRODUCTION)
        self.assertNotIn(DEV_ONLY, walls)
        self.assertNotIn(EXAMPLE_WALL_ID, walls)
        self.assertNotIn(SYNTHETIC_WALL, walls)

    def test_debug_catalog_matrix(self) -> None:
        walls = {item["wallId"]: item for item in self.client.get("/v1/debug/walls").json()["walls"]}
        self.assertIn(PROD_WALL, walls)
        self.assertIn(DEV_ONLY, walls)
        self.assertEqual(walls[DEV_ONLY]["environment"], ENVIRONMENT_DEVELOPMENT_TEST)
        self.assertIn(EXAMPLE_WALL_ID, walls)
        self.assertNotIn("environment", walls[EXAMPLE_WALL_ID])
        self.assertIn(SYNTHETIC_WALL, walls)
        self.assertNotIn("environment", walls[SYNTHETIC_WALL])

    def test_production_query_cannot_select_debug_audience(self) -> None:
        walls = self.client.get("/v1/walls", params={"debug": "true", "audience": "DEBUG_TEST"}).json()["walls"]
        ids = [item["wallId"] for item in walls]
        self.assertEqual(ids, [PROD_WALL])

    def test_production_convenience_rejects_dev_only_wall(self) -> None:
        self.assertEqual(self.client.get(f"/v1/walls/{DEV_ONLY}/manifest").status_code, 404)
        self.assertEqual(self.client.get(f"/v1/walls/{EXAMPLE_WALL_ID}/manifest").status_code, 404)
        self.assertEqual(self.client.get(f"/v1/walls/{SYNTHETIC_WALL}/manifest").status_code, 404)
        production = self.client.get(f"/v1/walls/{PROD_WALL}/manifest")
        self.assertEqual(production.status_code, 200)
        self.assertEqual(production.json()["wallId"], PROD_WALL)

    def test_debug_convenience_resolves_dev_wall(self) -> None:
        response = self.client.get(f"/v1/debug/walls/{DEV_ONLY}/manifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["wallId"], DEV_ONLY)
        self.assertEqual(self.client.get(f"/v1/debug/walls/{EXAMPLE_WALL_ID}/manifest").status_code, 200)
        self.assertEqual(self.client.get(f"/v1/debug/walls/{SYNTHETIC_WALL}/manifest").status_code, 200)

    def test_exact_release_route_unchanged(self) -> None:
        response = self.client.get(_explicit_manifest_path(DEV_ONLY, "r000001"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["wallId"], DEV_ONLY)
        self.assertEqual(response.json()["releaseId"], "r000001")
        unknown = self.client.get(_explicit_manifest_path("wall_not_in_catalog_01", "r000001"))
        self.assertEqual(unknown.status_code, 404)

    def test_unknown_promotion_environment_fails_closed_on_catalog(self) -> None:
        bad = _record(wall_id=PROD_WALL, name="Prod", environment=ENVIRONMENT_PRODUCTION)
        bad["environment"] = "staging"
        with self.assertRaises(PromotionRecordError) as exc:
            decode_promotion_record(bad)
        self.assertEqual(exc.exception.code, "PROMOTION_ENVIRONMENT_INVALID")
        broken = MemoryStore(
            catalog=empty_catalog(),
            manifests={(PROD_WALL, "r000001"): _manifest(PROD_WALL)},
            assets={},
            promotions=[],
        )
        broken._promotions = [bad]
        response = TestClient(create_app(store=broken)).get("/v1/walls")
        self.assertEqual(response.status_code, 500)


class SourceBoundaryTests(unittest.TestCase):
    def test_production_promoter_has_no_dev_bypass(self) -> None:
        pipeline = (ROOT / "offline" / "catalog_promotion" / "pipeline.py").read_text(encoding="utf-8")
        cli = (ROOT / "offline" / "catalog_promotion" / "cli.py").read_text(encoding="utf-8")
        self.assertNotIn("allow-dev", pipeline)
        self.assertNotIn("allow-dev", cli)
        self.assertNotIn("ENVIRONMENT_DEVELOPMENT_TEST", pipeline)
        self.assertIn("environment=ENVIRONMENT_PRODUCTION", pipeline)
        self.assertIn("TYPE_DESCRIPTORS", pipeline)
        self.assertIn("TYPE_LANDMARKS", pipeline)
        self.assertIn("TYPE_S_WALL_COLMAP", pipeline)
        self.assertIn("REMOTE_DESCRIPTORS_MISSING", pipeline)
        self.assertIn("REMOTE_LANDMARKS_MISSING", pipeline)
        self.assertIn("REMOTE_SIM3_MISSING", pipeline)
        publisher = (ROOT / "offline" / "publisher" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn("DEVELOPMENT_PACKAGE_NOT_PUBLISHABLE", publisher)
        self.assertIn("ENVIRONMENT_DEVELOPMENT_TEST", publisher)

    def test_development_promotion_is_separate_implemented_contract(self) -> None:
        source = (ROOT / "offline" / "catalog_promotion" / "development_promotion.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("promote_development_test_release", source)
        self.assertIn("DEVELOPMENT_TEST_ENVIRONMENT", source)
        self.assertNotIn("allow-dev", source)
        self.assertNotIn("environment=ENVIRONMENT_PRODUCTION", source)
        self.assertNotIn("DevelopmentPromotionNotImplemented", source)
        cli = (ROOT / "offline" / "catalog_promotion" / "cli.py").read_text(encoding="utf-8")
        self.assertNotIn("promote_development_test_release", cli)
        self.assertNotIn("wall_jiulongfeng_01_dev", cli)
        tree = ast.parse(source)
        fn = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "promote_development_test_release"
        )
        arg_names = [arg.arg for arg in [*fn.args.args, *fn.args.kwonlyargs]]
        self.assertNotIn("environment", arg_names)

    def test_jiulongfeng_like_dev_record_is_debug_only(self) -> None:
        record = _record(
            wall_id="wall_jiulongfeng_01_dev",
            name="Jiulongfeng Development Wall",
            environment=ENVIRONMENT_DEVELOPMENT_TEST,
        )
        production = filter_catalog_for_audience(project_promotions([record]), AUDIENCE_PRODUCTION)
        debug = filter_catalog_for_audience(project_promotions([record]), AUDIENCE_DEBUG_TEST)
        self.assertEqual(production["walls"], [])
        self.assertEqual(debug["walls"][0]["wallId"], "wall_jiulongfeng_01_dev")
        self.assertEqual(debug["walls"][0]["environment"], ENVIRONMENT_DEVELOPMENT_TEST)


if __name__ == "__main__":
    unittest.main()
