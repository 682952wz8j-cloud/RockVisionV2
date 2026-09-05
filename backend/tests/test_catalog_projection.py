"""Backend catalog projection and transitional legacy merge. No real COS."""

from __future__ import annotations

import inspect
import json
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient
from qcloud_cos.cos_exception import CosServiceError

from app.catalog_projection import ProjectionError, merge_legacy_and_projected, project_promotions
from app.contract import (
    CATALOG_SCHEMA,
    empty_catalog,
    published_catalog_key,
    published_manifest_key,
    published_promotion_key,
    published_promotions_prefix,
    validate_catalog,
    ContractError,
)
from app.cos_store import CosStore, REQUIRED_ENV
from app.main import create_app
from app.memory_store import (
    EXAMPLE_ASSET_BYTES,
    EXAMPLE_ASSET_ID,
    EXAMPLE_RELEASE_ID,
    EXAMPLE_RELEASE_ID_2,
    EXAMPLE_WALL_ID,
    MemoryStore,
    example_catalog,
    example_manifest,
)
from app.promotion import promotion_record
from app.store import StorageFailure

from tests.test_api import FakeCosClient, _client, _cos_example_client, _explicit_manifest_path

SYNTHETIC_WALL = "wall_publisher_e2e_01"
SYNTHETIC_NAME = "CragPal Publisher E2E Test Wall"
SYNTHETIC_RELEASE = "r000001"
WHEN = "2026-09-04T15:48:58Z"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _record(
    *,
    wall_id: str = SYNTHETIC_WALL,
    release_id: str = SYNTHETIC_RELEASE,
    name: str = SYNTHETIC_NAME,
    sha: str = SHA_A,
    promoted_at: str = WHEN,
    environment: str | None = None,
) -> dict:
    return promotion_record(
        wall_id=wall_id,
        release_id=release_id,
        name=name,
        promoted_at=promoted_at,
        release_manifest_sha256=sha,
        environment=environment,
    )


def _legacy(
    *,
    wall_id: str = EXAMPLE_WALL_ID,
    name: str = "Example Wall",
    latest: str = EXAMPLE_RELEASE_ID,
) -> dict:
    return {
        "schema": CATALOG_SCHEMA,
        "walls": [{"wallId": wall_id, "name": name, "latestReleaseId": latest}],
    }


def _put_json(client: FakeCosClient, key: str, payload: dict) -> None:
    client.objects[key] = json.dumps(payload).encode("utf-8")


def _synthetic_manifest() -> dict:
    payload = example_manifest()
    payload["wallId"] = SYNTHETIC_WALL
    payload["releaseId"] = SYNTHETIC_RELEASE
    return payload


class MergeSemanticsTests(unittest.TestCase):
    def test_01_legacy_only_catalog(self) -> None:
        merged = merge_legacy_and_projected(_legacy(), project_promotions([]))
        self.assertEqual(merged["schema"], CATALOG_SCHEMA)
        self.assertEqual(merged["walls"][0]["wallId"], EXAMPLE_WALL_ID)
        self.assertEqual(merged["walls"][0]["latestReleaseId"], EXAMPLE_RELEASE_ID)

    def test_02_promotions_only_catalog(self) -> None:
        merged = merge_legacy_and_projected(empty_catalog(), project_promotions([_record()]))
        self.assertEqual(merged["walls"][0]["wallId"], SYNTHETIC_WALL)
        self.assertEqual(merged["walls"][0]["name"], SYNTHETIC_NAME)
        self.assertEqual(merged["walls"][0]["latestReleaseId"], SYNTHETIC_RELEASE)

    def test_03_legacy_and_promotion_different_walls(self) -> None:
        merged = merge_legacy_and_projected(_legacy(), project_promotions([_record()]))
        wall_ids = [item["wallId"] for item in merged["walls"]]
        self.assertEqual(wall_ids, [EXAMPLE_WALL_ID, SYNTHETIC_WALL])
        by_id = {item["wallId"]: item for item in merged["walls"]}
        self.assertEqual(by_id[EXAMPLE_WALL_ID]["latestReleaseId"], EXAMPLE_RELEASE_ID)
        self.assertEqual(by_id[SYNTHETIC_WALL]["name"], SYNTHETIC_NAME)

    def test_04_same_wall_same_name_promotion_latest_wins(self) -> None:
        legacy = _legacy(latest=EXAMPLE_RELEASE_ID)
        projected = project_promotions(
            [_record(wall_id=EXAMPLE_WALL_ID, release_id=EXAMPLE_RELEASE_ID_2, name="Example Wall", sha=SHA_B)]
        )
        merged = merge_legacy_and_projected(legacy, projected)
        self.assertEqual(len(merged["walls"]), 1)
        self.assertEqual(merged["walls"][0]["name"], "Example Wall")
        self.assertEqual(merged["walls"][0]["latestReleaseId"], EXAMPLE_RELEASE_ID_2)

    def test_05_same_wall_conflicting_name_fails_closed(self) -> None:
        with self.assertRaises(ProjectionError) as exc:
            merge_legacy_and_projected(
                _legacy(name="Example Wall"),
                project_promotions([_record(wall_id=EXAMPLE_WALL_ID, name="Other Name")]),
            )
        self.assertEqual(exc.exception.code, "LEGACY_PROMOTION_NAME_CONFLICT")

    def test_06_multiple_promotion_releases_highest_ordinal(self) -> None:
        catalog = project_promotions(
            [
                _record(release_id="r000001", sha=SHA_A),
                _record(release_id="r000010", sha=SHA_B),
                _record(release_id="r000002", sha=SHA_C),
            ]
        )
        self.assertEqual(catalog["walls"][0]["latestReleaseId"], "r000010")

    def test_07_malformed_promotion_fails_closed(self) -> None:
        with self.assertRaises(ProjectionError) as exc:
            project_promotions([{"not": "a promotion"}])
        self.assertIn(exc.exception.code, {"PROMOTION_RECORD_INVALID", "PROMOTION_SCHEMA_UNSUPPORTED"})

    def test_08_unsupported_promotion_schema_fails_closed(self) -> None:
        with self.assertRaises(ProjectionError) as exc:
            project_promotions([{"schema": "cragpal.wall-promotion.v2", "wallId": SYNTHETIC_WALL}])
        self.assertEqual(exc.exception.code, "PROMOTION_SCHEMA_UNSUPPORTED")

    def test_09_malformed_legacy_catalog_fails_closed(self) -> None:
        with self.assertRaises(ContractError):
            validate_catalog({"schema": CATALOG_SCHEMA, "walls": "nope"})

    def test_10_unsupported_legacy_schema_fails_closed(self) -> None:
        with self.assertRaises(ContractError):
            validate_catalog({"schema": "cragpal.wall-catalog.v0", "walls": []})

    def test_duplicate_conflicting_promotion_bytes_fail_closed(self) -> None:
        a = _record(sha=SHA_A)
        b = _record(sha=SHA_B, promoted_at="2026-09-04T16:00:00Z")
        with self.assertRaises(ProjectionError) as exc:
            project_promotions([a, b])
        self.assertEqual(exc.exception.code, "PROMOTION_IDENTITY_CONFLICT")

    def test_intra_promotion_name_conflict_fails_closed(self) -> None:
        with self.assertRaises(ProjectionError) as exc:
            project_promotions(
                [
                    _record(release_id="r000001", name=SYNTHETIC_NAME),
                    _record(release_id="r000002", name="Other"),
                ]
            )
        self.assertEqual(exc.exception.code, "PROMOTION_NAME_CONFLICT")


class CatalogApiProjectionTests(unittest.TestCase):
    def test_11_v1_walls_returns_merged_catalog(self) -> None:
        store = MemoryStore(
            catalog=example_catalog(),
            manifests={
                (EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID): example_manifest(),
                (SYNTHETIC_WALL, SYNTHETIC_RELEASE): _synthetic_manifest(),
            },
            assets={(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID, EXAMPLE_ASSET_ID): EXAMPLE_ASSET_BYTES},
            promotions=[_record()],
        )
        production = _client(store).get("/v1/walls")
        self.assertEqual(production.status_code, 200)
        self.assertEqual(production.json()["walls"], [])
        response = _client(store).get("/v1/debug/walls")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema"], CATALOG_SCHEMA)
        self.assertEqual(
            [item["wallId"] for item in payload["walls"]],
            [EXAMPLE_WALL_ID, SYNTHETIC_WALL],
        )

    def test_12_convenience_manifest_uses_merged_latest(self) -> None:
        store = MemoryStore(
            catalog=_legacy(latest=EXAMPLE_RELEASE_ID),
            manifests={
                (EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID): example_manifest(),
                (EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID_2): example_manifest(release_id=EXAMPLE_RELEASE_ID_2),
            },
            assets={
                (EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID, EXAMPLE_ASSET_ID): EXAMPLE_ASSET_BYTES,
            },
            promotions=[
                _record(
                    wall_id=EXAMPLE_WALL_ID,
                    release_id=EXAMPLE_RELEASE_ID_2,
                    name="Example Wall",
                    sha=SHA_B,
                )
            ],
        )
        catalog = _client(store).get("/v1/debug/walls")
        self.assertEqual(catalog.json()["walls"][0]["latestReleaseId"], EXAMPLE_RELEASE_ID_2)
        self.assertEqual(_client(store).get("/v1/walls").json()["walls"], [])
        convenience = _client(store).get(f"/v1/debug/walls/{EXAMPLE_WALL_ID}/manifest")
        self.assertEqual(convenience.status_code, 200)
        self.assertEqual(convenience.json()["releaseId"], EXAMPLE_RELEASE_ID_2)
        self.assertEqual(
            _client(store).get(f"/v1/walls/{EXAMPLE_WALL_ID}/manifest").status_code,
            404,
        )

    def test_13_release_scoped_manifest_unchanged(self) -> None:
        fake = FakeCosClient()
        payload = _synthetic_manifest()
        _put_json(fake, published_manifest_key(SYNTHETIC_WALL, SYNTHETIC_RELEASE), payload)
        store = CosStore(client=fake, bucket="example-bucket")
        response = _client(store).get(_explicit_manifest_path(SYNTHETIC_WALL, SYNTHETIC_RELEASE))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["wallId"], SYNTHETIC_WALL)
        self.assertNotIn(published_catalog_key(), fake.accessed_keys)
        self.assertEqual(fake.listed_prefixes, [])
        self.assertEqual(
            fake.accessed_keys,
            [published_manifest_key(SYNTHETIC_WALL, SYNTHETIC_RELEASE)],
        )

    def test_14_unknown_wall_returns_404(self) -> None:
        response = _client().get("/v1/walls/wall_unknown_99/manifest")
        self.assertEqual(response.status_code, 404)

    def test_15_promotion_only_wall_convenience_manifest(self) -> None:
        store = MemoryStore(
            catalog=empty_catalog(),
            manifests={(SYNTHETIC_WALL, SYNTHETIC_RELEASE): _synthetic_manifest()},
            assets={},
            promotions=[_record()],
        )
        catalog = _client(store).get("/v1/debug/walls")
        self.assertEqual(catalog.json()["walls"][0]["wallId"], SYNTHETIC_WALL)
        self.assertEqual(_client(store).get("/v1/walls").json()["walls"], [])
        convenience = _client(store).get(f"/v1/debug/walls/{SYNTHETIC_WALL}/manifest")
        self.assertEqual(convenience.status_code, 200)
        self.assertEqual(convenience.json()["releaseId"], SYNTHETIC_RELEASE)
        self.assertEqual(convenience.json()["wallId"], SYNTHETIC_WALL)
        self.assertEqual(_client(store).get(f"/v1/walls/{SYNTHETIC_WALL}/manifest").status_code, 404)

    def test_16_legacy_only_wall_convenience_manifest_still_works(self) -> None:
        self.assertEqual(_client().get(f"/v1/walls/{EXAMPLE_WALL_ID}/manifest").status_code, 404)
        response = _client().get(f"/v1/debug/walls/{EXAMPLE_WALL_ID}/manifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["releaseId"], EXAMPLE_RELEASE_ID)

    def test_cos_merged_view_matches_theoretical_production_data(self) -> None:
        fake = _cos_example_client()
        _put_json(fake, published_promotion_key(SYNTHETIC_WALL, SYNTHETIC_RELEASE), _record())
        _put_json(fake, published_manifest_key(SYNTHETIC_WALL, SYNTHETIC_RELEASE), _synthetic_manifest())
        store = CosStore(client=fake, bucket="example-bucket")
        client = _client(store)
        catalog = client.get("/v1/walls")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.json()["walls"], [])
        debug = client.get("/v1/debug/walls")
        self.assertEqual(
            [item["wallId"] for item in debug.json()["walls"]],
            [EXAMPLE_WALL_ID, SYNTHETIC_WALL],
        )
        convenience = client.get(f"/v1/debug/walls/{SYNTHETIC_WALL}/manifest")
        self.assertEqual(convenience.status_code, 200)
        self.assertEqual(convenience.json()["releaseId"], SYNTHETIC_RELEASE)
        self.assertEqual(client.get(f"/v1/walls/{SYNTHETIC_WALL}/manifest").status_code, 404)
        self.assertTrue(fake.listed_prefixes)
        self.assertEqual(set(fake.listed_prefixes), {published_promotions_prefix()})
        self.assertEqual(fake.write_attempts, [])

    def test_malformed_promotion_object_returns_500(self) -> None:
        fake = _cos_example_client()
        fake.objects[published_promotion_key(SYNTHETIC_WALL, SYNTHETIC_RELEASE)] = b"{not-json"
        response = _client(CosStore(client=fake, bucket="example-bucket")).get("/v1/walls")
        self.assertEqual(response.status_code, 500)

    def test_unsupported_promotion_schema_returns_500(self) -> None:
        fake = _cos_example_client()
        _put_json(
            fake,
            published_promotion_key(SYNTHETIC_WALL, SYNTHETIC_RELEASE),
            {"schema": "cragpal.wall-promotion.v2", "wallId": SYNTHETIC_WALL},
        )
        response = _client(CosStore(client=fake, bucket="example-bucket")).get("/v1/walls")
        self.assertEqual(response.status_code, 500)

    def test_malformed_legacy_catalog_returns_500(self) -> None:
        fake = FakeCosClient()
        fake.objects[published_catalog_key()] = b"not-json"
        response = _client(CosStore(client=fake, bucket="example-bucket")).get("/v1/walls")
        self.assertEqual(response.status_code, 500)

    def test_unsupported_legacy_schema_returns_500(self) -> None:
        fake = FakeCosClient()
        _put_json(fake, published_catalog_key(), {"schema": "cragpal.wall-catalog.v0", "walls": []})
        response = _client(CosStore(client=fake, bucket="example-bucket")).get("/v1/walls")
        self.assertEqual(response.status_code, 500)

    def test_legacy_promotion_name_conflict_returns_500(self) -> None:
        fake = _cos_example_client()
        _put_json(
            fake,
            published_promotion_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID),
            _record(wall_id=EXAMPLE_WALL_ID, name="Different"),
        )
        response = _client(CosStore(client=fake, bucket="example-bucket")).get("/v1/walls")
        self.assertEqual(response.status_code, 500)

    def test_unexpected_promotion_key_fails_closed(self) -> None:
        fake = _cos_example_client()
        fake.objects["published/promotions/readme.txt"] = b"nope"
        response = _client(CosStore(client=fake, bucket="example-bucket")).get("/v1/walls")
        self.assertEqual(response.status_code, 500)

    def test_list_denied_does_not_silently_serve_legacy_only(self) -> None:
        fake = _cos_example_client()
        fake.list_errors[published_promotions_prefix()] = CosServiceError(
            "GET",
            {"code": "AccessDenied", "message": "denied", "resource": "x", "requestid": "", "traceid": ""},
            403,
        )
        store = CosStore(client=fake, bucket="example-bucket")
        with self.assertRaises(StorageFailure):
            store.catalog()
        response = _client(store).get("/v1/walls")
        self.assertEqual(response.status_code, 502)
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn("AccessDenied", response.text)


class ReadOnlyAndIdentityTests(unittest.TestCase):
    def test_17_no_backend_puts_in_cos_store(self) -> None:
        source = Path(inspect.getsourcefile(CosStore)).read_text(encoding="utf-8")
        self.assertNotIn("put_object", source)
        self.assertNotIn("delete_object", source)
        self.assertNotIn("DeleteObject", source)
        self.assertIn("list_objects", source)
        fake = _cos_example_client()
        _client(CosStore(client=fake, bucket="example-bucket")).get("/v1/walls")
        self.assertEqual(fake.write_attempts, [])

    def test_18_no_catalog_mutation(self) -> None:
        fake = _cos_example_client()
        before = fake.objects[published_catalog_key()]
        _client(CosStore(client=fake, bucket="example-bucket")).get("/v1/walls")
        self.assertEqual(fake.objects[published_catalog_key()], before)
        self.assertEqual(fake.write_attempts, [])

    def test_19_no_publisher_identity_usage(self) -> None:
        source = Path(inspect.getsourcefile(CosStore)).read_text(encoding="utf-8")
        self.assertNotIn("CRAGPAL_PUBLISHER", source)
        self.assertEqual(
            REQUIRED_ENV,
            (
                "TENCENT_COS_REGION",
                "TENCENT_SECRET_ID",
                "TENCENT_SECRET_KEY",
                "TENCENT_COS_BUCKET",
            ),
        )
        self.assertNotIn("CRAGPAL_PUBLISHER_SECRET_ID", REQUIRED_ENV)

    def test_20_runtime_read_only_semantics_preserved(self) -> None:
        fake = _cos_example_client()
        store = CosStore(client=fake, bucket="example-bucket")
        self.assertFalse(hasattr(store, "put_bytes"))
        self.assertFalse(hasattr(store, "put_if_absent"))
        self.assertFalse(callable(getattr(store, "put_object", None)))
        catalog = store.catalog()
        validate_catalog(catalog)
        explicit = _client(store).get(_explicit_manifest_path(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID))
        self.assertEqual(explicit.status_code, 200)
        self.assertEqual(explicit.json()["releaseId"], EXAMPLE_RELEASE_ID)

    def test_list_uses_promotions_prefix_only(self) -> None:
        fake = _cos_example_client()
        CosStore(client=fake, bucket="example-bucket").catalog()
        self.assertEqual(fake.listed_prefixes, [published_promotions_prefix()])
        self.assertNotIn("", fake.listed_prefixes)
        self.assertNotIn("published/", fake.listed_prefixes)


class MemoryStoreProjectionTests(unittest.TestCase):
    def test_mutating_legacy_catalog_still_affects_view_without_promotions(self) -> None:
        store = MemoryStore.two_releases(latest_release_id=EXAMPLE_RELEASE_ID)
        client = TestClient(create_app(store=store))
        self.assertEqual(client.get(f"/v1/debug/walls/{EXAMPLE_WALL_ID}/manifest").json()["releaseId"], EXAMPLE_RELEASE_ID)
        store._catalog["walls"][0]["latestReleaseId"] = EXAMPLE_RELEASE_ID_2
        self.assertEqual(client.get(f"/v1/debug/walls/{EXAMPLE_WALL_ID}/manifest").json()["releaseId"], EXAMPLE_RELEASE_ID_2)


if __name__ == "__main__":
    unittest.main()
