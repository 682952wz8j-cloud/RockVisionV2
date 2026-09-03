"""Cloud Asset API v1 tests. No Tencent credentials or network."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient
from qcloud_cos.cos_exception import CosClientError, CosServiceError

from app.contract import (
    CATALOG_SCHEMA,
    MANIFEST_SCHEMA,
    SHA256_RE,
    assert_manifest_identity,
    published_asset_key,
    published_catalog_key,
    published_manifest_key,
    validate_manifest,
    ContractError,
)
from app.cos_store import CosStore
from app.main import create_app
from app.memory_store import (
    EXAMPLE_ASSET_BYTES,
    EXAMPLE_ASSET_BYTES_V2,
    EXAMPLE_ASSET_ID,
    EXAMPLE_ASSET_SHA256,
    EXAMPLE_RELEASE_ID,
    EXAMPLE_RELEASE_ID_2,
    EXAMPLE_WALL_ID,
    MemoryStore,
    example_catalog,
    example_manifest,
)
from app.store import NotFound, StorageFailure, StorageUnavailable


def _client(store=None) -> TestClient:
    return TestClient(create_app(store=store or MemoryStore.example()))


def _asset_path(release_id: str = EXAMPLE_RELEASE_ID, asset_id: str = EXAMPLE_ASSET_ID) -> str:
    return f"/v1/walls/{EXAMPLE_WALL_ID}/releases/{release_id}/assets/{asset_id}"


class _FakeCosBody:
    def __init__(self, payload: bytes):
        self._payload = payload

    def get_raw_stream(self):
        return self


    def read(self):
        return self._payload


class FakeCosClient:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.errors: dict[str, Exception] = {}
        self.accessed_keys: list[str] = []

    def get_object(self, Bucket, Key):
        self.accessed_keys.append(Key)
        if Key in self.errors:
            raise self.errors[Key]
        if Key not in self.objects:
            raise CosServiceError(
                "GET",
                {"code": "NoSuchKey", "message": "missing", "resource": Key, "requestid": "", "traceid": ""},
                404,
            )
        return {"Body": _FakeCosBody(self.objects[Key])}


def _cos_example_client() -> FakeCosClient:
    client = FakeCosClient()
    client.objects[published_catalog_key()] = json.dumps(example_catalog()).encode("utf-8")
    client.objects[published_manifest_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)] = json.dumps(
        example_manifest()
    ).encode("utf-8")
    client.objects[published_asset_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID, EXAMPLE_ASSET_ID)] = (
        EXAMPLE_ASSET_BYTES
    )
    return client


class HealthTests(unittest.TestCase):
    def test_health_returns_200(self) -> None:
        response = _client().get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_health_does_not_require_cos_credentials(self) -> None:
        saved = {
            name: os.environ.pop(name, None)
            for name in (
                "TENCENT_COS_REGION",
                "TENCENT_SECRET_ID",
                "TENCENT_SECRET_KEY",
                "TENCENT_COS_BUCKET",
                "CRAGPAL_ASSET_STORE",
            )
        }
        try:
            client = TestClient(create_app())
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get("/v1/walls").status_code, 503)
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


class CatalogTests(unittest.TestCase):
    def test_walls_returns_catalog_schema(self) -> None:
        response = _client().get("/v1/walls")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema"], CATALOG_SCHEMA)
        self.assertEqual(payload["walls"][0]["wallId"], EXAMPLE_WALL_ID)
        self.assertEqual(payload["walls"][0]["latestReleaseId"], EXAMPLE_RELEASE_ID)
        self.assertNotIn("secretId", str(payload))
        self.assertNotIn("SecretKey", str(payload))


class ManifestTests(unittest.TestCase):
    def test_known_wall_manifest_returns_r000001(self) -> None:
        response = _client().get(f"/v1/walls/{EXAMPLE_WALL_ID}/manifest")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema"], MANIFEST_SCHEMA)
        self.assertEqual(payload["wallId"], EXAMPLE_WALL_ID)
        self.assertEqual(payload["releaseId"], EXAMPLE_RELEASE_ID)
        asset = payload["assets"][0]
        self.assertEqual(asset["assetId"], EXAMPLE_ASSET_ID)
        self.assertEqual(asset["type"], "reference_map")
        self.assertTrue(asset["required"])
        self.assertEqual(asset["bytes"], len(EXAMPLE_ASSET_BYTES))
        self.assertRegex(asset["sha256"], SHA256_RE.pattern)
        self.assertNotIn("objectKey", payload)
        self.assertNotIn("bucket", payload)

    def test_unknown_wall_returns_404(self) -> None:
        response = _client().get("/v1/walls/wall_unknown_99/manifest")
        self.assertEqual(response.status_code, 404)


DEV_WALL_ID = "wall_jiulongfeng_01_dev"


def _dev_manifest() -> dict:
    payload = example_manifest()
    payload["wallId"] = DEV_WALL_ID
    return payload


def _explicit_manifest_path(wall_id: str = DEV_WALL_ID, release_id: str = EXAMPLE_RELEASE_ID) -> str:
    return f"/v1/walls/{wall_id}/releases/{release_id}/manifest"


class ExplicitManifestTests(unittest.TestCase):
    def test_valid_explicit_manifest_returns_200_without_catalog_membership(self) -> None:
        store = MemoryStore(
            catalog=example_catalog(),
            manifests={
                (EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID): example_manifest(),
                (DEV_WALL_ID, EXAMPLE_RELEASE_ID): _dev_manifest(),
            },
            assets={(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID, EXAMPLE_ASSET_ID): EXAMPLE_ASSET_BYTES},
        )
        client = _client(store)
        catalog = client.get("/v1/walls")
        self.assertEqual(catalog.status_code, 200)
        wall_ids = [item["wallId"] for item in catalog.json()["walls"]]
        self.assertEqual(wall_ids, [EXAMPLE_WALL_ID])
        self.assertNotIn(DEV_WALL_ID, wall_ids)

        convenience = client.get(f"/v1/walls/{DEV_WALL_ID}/manifest")
        self.assertEqual(convenience.status_code, 404)

        response = client.get(_explicit_manifest_path())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema"], MANIFEST_SCHEMA)
        self.assertEqual(payload["wallId"], DEV_WALL_ID)
        self.assertEqual(payload["releaseId"], EXAMPLE_RELEASE_ID)

    def test_explicit_manifest_identity_matches_request(self) -> None:
        response = _client().get(_explicit_manifest_path(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["wallId"], EXAMPLE_WALL_ID)
        self.assertEqual(payload["releaseId"], EXAMPLE_RELEASE_ID)

    def test_unknown_explicit_release_returns_404(self) -> None:
        response = _client().get(_explicit_manifest_path(EXAMPLE_WALL_ID, "r000099"))
        self.assertEqual(response.status_code, 404)
        response = _client().get(_explicit_manifest_path("wall_unknown_99", EXAMPLE_RELEASE_ID))
        self.assertEqual(response.status_code, 404)

    def test_unsafe_wall_id_returns_400(self) -> None:
        response = _client().get("/v1/walls/a:b/releases/r000001/manifest")
        self.assertEqual(response.status_code, 400)

    def test_unsafe_release_id_returns_400(self) -> None:
        for release_id in ("latest", "r1", "r00001", "R000001", "r000001a"):
            response = _client().get(_explicit_manifest_path(EXAMPLE_WALL_ID, release_id))
            self.assertEqual(response.status_code, 400, release_id)

    def test_malformed_published_json_returns_500(self) -> None:
        client = _cos_example_client()
        client.objects[published_manifest_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)] = b"not-json"
        store = CosStore(client=client, bucket="example-bucket")
        response = _client(store).get(_explicit_manifest_path(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID))
        self.assertEqual(response.status_code, 500)
        self.assertNotEqual(response.status_code, 404)

    def test_wall_id_mismatch_returns_500(self) -> None:
        client = _cos_example_client()
        payload = example_manifest()
        payload["wallId"] = "wall_other_01"
        client.objects[published_manifest_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)] = json.dumps(
            payload
        ).encode("utf-8")
        store = CosStore(client=client, bucket="example-bucket")
        response = _client(store).get(_explicit_manifest_path(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID))
        self.assertEqual(response.status_code, 500)

    def test_release_id_mismatch_returns_500(self) -> None:
        client = _cos_example_client()
        payload = example_manifest()
        payload["releaseId"] = EXAMPLE_RELEASE_ID_2
        client.objects[published_manifest_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)] = json.dumps(
            payload
        ).encode("utf-8")
        store = CosStore(client=client, bucket="example-bucket")
        response = _client(store).get(_explicit_manifest_path(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID))
        self.assertEqual(response.status_code, 500)

    def test_cos_auth_failure_returns_502(self) -> None:
        client = FakeCosClient()
        client.errors[published_manifest_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)] = CosServiceError(
            "GET",
            {"code": "AccessDenied", "message": "denied", "resource": "x", "requestid": "", "traceid": ""},
            403,
        )
        store = CosStore(client=client, bucket="example-bucket")
        response = _client(store).get(_explicit_manifest_path(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID))
        self.assertEqual(response.status_code, 502)
        self.assertNotEqual(response.status_code, 404)
        self.assertNotIn("AccessDenied", response.text)

    def test_cos_network_failure_returns_502(self) -> None:
        client = FakeCosClient()
        client.errors[published_manifest_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)] = CosClientError("timeout")
        store = CosStore(client=client, bucket="example-bucket")
        response = _client(store).get(_explicit_manifest_path(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID))
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("timeout", response.text)

    def test_missing_cos_configuration_returns_503(self) -> None:
        saved = {
            name: os.environ.pop(name, None)
            for name in (
                "TENCENT_COS_REGION",
                "TENCENT_SECRET_ID",
                "TENCENT_SECRET_KEY",
                "TENCENT_COS_BUCKET",
                "CRAGPAL_ASSET_STORE",
            )
        }
        try:
            client = TestClient(create_app())
            response = client.get(_explicit_manifest_path(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID))
            self.assertEqual(response.status_code, 503)
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_existing_convenience_manifest_and_asset_routes_unchanged(self) -> None:
        client = _client()
        catalog = client.get("/v1/walls")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.json()["walls"][0]["wallId"], EXAMPLE_WALL_ID)
        convenience = client.get(f"/v1/walls/{EXAMPLE_WALL_ID}/manifest")
        self.assertEqual(convenience.status_code, 200)
        self.assertEqual(convenience.json()["releaseId"], EXAMPLE_RELEASE_ID)
        asset = client.get(_asset_path())
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.content, EXAMPLE_ASSET_BYTES)

    def test_explicit_manifest_does_not_read_catalog(self) -> None:
        fake = FakeCosClient()
        payload = _dev_manifest()
        fake.objects[published_manifest_key(DEV_WALL_ID, EXAMPLE_RELEASE_ID)] = json.dumps(
            payload
        ).encode("utf-8")
        store = CosStore(client=fake, bucket="example-bucket")
        response = _client(store).get(_explicit_manifest_path())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["wallId"], DEV_WALL_ID)
        self.assertNotIn(published_catalog_key(), fake.accessed_keys)
        self.assertEqual(
            fake.accessed_keys,
            [published_manifest_key(DEV_WALL_ID, EXAMPLE_RELEASE_ID)],
        )
        convenience = _client(store).get(f"/v1/walls/{DEV_WALL_ID}/manifest")
        self.assertEqual(convenience.status_code, 404)


class AssetTests(unittest.TestCase):
    def test_known_release_asset_returned_from_store(self) -> None:
        response = _client().get(_asset_path())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, EXAMPLE_ASSET_BYTES)
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), EXAMPLE_ASSET_SHA256)
        self.assertEqual(int(response.headers["content-length"]), len(EXAMPLE_ASSET_BYTES))
        self.assertEqual(response.headers["x-cragpal-release-id"], EXAMPLE_RELEASE_ID)

    def test_invalid_release_id_returns_400(self) -> None:
        for release_id in ("latest", "r1", "r00001", "R000001", "r000001a"):
            response = _client().get(_asset_path(release_id=release_id))
            self.assertEqual(response.status_code, 400, release_id)

    def test_slash_injection_in_release_id_is_rejected(self) -> None:
        response = _client().get(_asset_path(release_id="../r000001"))
        self.assertIn(response.status_code, {400, 404, 422})
        self.assertNotEqual(response.status_code, 200)

    def test_unknown_release_returns_404(self) -> None:
        response = _client().get(_asset_path(release_id="r000099"))
        self.assertEqual(response.status_code, 404)

    def test_unknown_asset_within_known_release_returns_404(self) -> None:
        response = _client().get(_asset_path(asset_id="missing-asset"))
        self.assertEqual(response.status_code, 404)

    def test_unknown_wall_asset_returns_404(self) -> None:
        response = _client().get(
            f"/v1/walls/wall_unknown_99/releases/{EXAMPLE_RELEASE_ID}/assets/{EXAMPLE_ASSET_ID}"
        )
        self.assertEqual(response.status_code, 404)


class ReleaseRaceTests(unittest.TestCase):
    def test_pinned_r000001_survives_latest_changing_to_r000002(self) -> None:
        store = MemoryStore.two_releases(latest_release_id=EXAMPLE_RELEASE_ID)
        client = _client(store)
        manifest = client.get(f"/v1/walls/{EXAMPLE_WALL_ID}/manifest")
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()["releaseId"], EXAMPLE_RELEASE_ID)

        store._catalog["walls"][0]["latestReleaseId"] = EXAMPLE_RELEASE_ID_2
        pinned = client.get(_asset_path(release_id=manifest.json()["releaseId"]))
        self.assertEqual(pinned.status_code, 200)
        self.assertEqual(pinned.content, EXAMPLE_ASSET_BYTES)
        self.assertNotEqual(pinned.content, EXAMPLE_ASSET_BYTES_V2)

        current = client.get(f"/v1/walls/{EXAMPLE_WALL_ID}/manifest")
        self.assertEqual(current.json()["releaseId"], EXAMPLE_RELEASE_ID_2)

    def test_requesting_r000002_returns_r000002_bytes(self) -> None:
        response = _client(MemoryStore.two_releases()).get(_asset_path(release_id=EXAMPLE_RELEASE_ID_2))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, EXAMPLE_ASSET_BYTES_V2)


class PathSafetyTests(unittest.TestCase):
    def test_path_traversal_wall_rejected(self) -> None:
        for wall_id in ("..", "../etc", "wall/../../secret", "wall/foo", "a:b", "wall\\x"):
            response = _client().get(f"/v1/walls/{wall_id}/manifest")
            self.assertIn(response.status_code, {400, 404, 307, 422}, wall_id)
            self.assertNotEqual(response.status_code, 200, wall_id)

    def test_path_traversal_asset_rejected(self) -> None:
        for asset_id in ("..", "../secret", "a/b", "published/catalog.json", "..%2Fsecret"):
            response = _client().get(_asset_path(asset_id=asset_id))
            self.assertIn(response.status_code, {400, 404, 422}, asset_id)
            self.assertNotEqual(response.status_code, 200, asset_id)

    def test_no_arbitrary_cos_path_endpoint(self) -> None:
        client = _client()
        for path in (
            "/cos-test",
            "/assets/published/catalog.json",
            "/v1/assets/published/catalog.json",
            f"/v1/walls/{EXAMPLE_WALL_ID}/assets/{EXAMPLE_ASSET_ID}",
            f"/v1/walls/{EXAMPLE_WALL_ID}/assets/published/{EXAMPLE_WALL_ID}/r000001/assets/{EXAMPLE_ASSET_ID}",
            f"/v1/walls/{EXAMPLE_WALL_ID}/releases/{EXAMPLE_RELEASE_ID}/assets/published/{EXAMPLE_WALL_ID}/r000001/assets/{EXAMPLE_ASSET_ID}",
        ):
            response = client.get(path)
            self.assertIn(response.status_code, {400, 404, 405, 422}, path)

    def test_backend_owned_keys_are_not_caller_input(self) -> None:
        self.assertEqual(published_catalog_key(), "published/catalog.json")
        self.assertEqual(
            published_manifest_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID),
            "published/wall_example_01/r000001/manifest.json",
        )
        self.assertEqual(
            published_asset_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID, EXAMPLE_ASSET_ID),
            "published/wall_example_01/r000001/assets/reference-map",
        )
        with self.assertRaises(ContractError):
            published_asset_key("../etc", EXAMPLE_RELEASE_ID, "passwd")
        with self.assertRaises(ContractError):
            published_asset_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID, "a/b")


class ManifestValidationTests(unittest.TestCase):
    def test_sha256_must_be_64_lowercase_hex(self) -> None:
        payload = example_manifest()
        payload["assets"][0]["sha256"] = "NOT-A-HASH"
        with self.assertRaises(ContractError):
            validate_manifest(payload)

    def test_bytes_must_be_non_negative(self) -> None:
        payload = example_manifest()
        payload["assets"][0]["bytes"] = -1
        with self.assertRaises(ContractError):
            validate_manifest(payload)

    def test_duplicate_asset_id_rejected(self) -> None:
        payload = example_manifest()
        payload["assets"].append(dict(payload["assets"][0]))
        with self.assertRaises(ContractError):
            validate_manifest(payload)

    def test_memory_store_rejects_invalid_manifest_at_construction(self) -> None:
        payload = example_manifest()
        payload["assets"][0]["bytes"] = -5
        with self.assertRaises(ContractError):
            MemoryStore(
                catalog=example_catalog(),
                manifests={(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID): payload},
                assets={},
            )

    def test_manifest_wall_id_mismatch_rejected_by_shared_contract(self) -> None:
        payload = example_manifest()
        payload["wallId"] = "wall_other_01"
        with self.assertRaises(ContractError):
            assert_manifest_identity(payload, EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)

    def test_manifest_release_id_mismatch_rejected_by_shared_contract(self) -> None:
        payload = example_manifest()
        payload["releaseId"] = EXAMPLE_RELEASE_ID_2
        with self.assertRaises(ContractError):
            assert_manifest_identity(payload, EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)

    def test_memory_store_rejects_manifest_wall_id_mismatch(self) -> None:
        payload = example_manifest()
        payload["wallId"] = "wall_other_01"
        with self.assertRaises(ContractError):
            MemoryStore(
                catalog=example_catalog(),
                manifests={(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID): payload},
                assets={},
            )

    def test_memory_store_rejects_manifest_release_id_mismatch(self) -> None:
        payload = example_manifest()
        payload["releaseId"] = EXAMPLE_RELEASE_ID_2
        with self.assertRaises(ContractError):
            MemoryStore(
                catalog=example_catalog(),
                manifests={(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID): payload},
                assets={},
            )

    def test_cos_store_rejects_manifest_wall_id_mismatch(self) -> None:
        client = _cos_example_client()
        payload = example_manifest()
        payload["wallId"] = "wall_other_01"
        client.objects[published_manifest_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)] = json.dumps(
            payload
        ).encode("utf-8")
        store = CosStore(client=client, bucket="example-bucket")
        with self.assertRaises(ContractError):
            store.manifest_for_release(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)

    def test_cos_store_rejects_manifest_release_id_mismatch(self) -> None:
        client = _cos_example_client()
        payload = example_manifest()
        payload["releaseId"] = EXAMPLE_RELEASE_ID_2
        client.objects[published_manifest_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)] = json.dumps(
            payload
        ).encode("utf-8")
        store = CosStore(client=client, bucket="example-bucket")
        with self.assertRaises(ContractError):
            store.manifest_for_release(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID)


class PublicSurfaceTests(unittest.TestCase):
    def test_temporary_and_unpinned_routes_are_not_registered(self) -> None:
        routes = {getattr(route, "path", "") for route in create_app().routes}
        self.assertNotIn("/cos-test", routes)
        self.assertNotIn("/assets/{asset_path}", routes)
        self.assertNotIn("/v1/walls/{wall_id}/assets/{asset_id}", routes)
        self.assertIn("/health", routes)
        self.assertIn("/v1/walls", routes)
        self.assertIn("/v1/walls/{wall_id}/manifest", routes)
        self.assertIn("/v1/walls/{wall_id}/releases/{release_id}/manifest", routes)
        self.assertIn("/v1/walls/{wall_id}/releases/{release_id}/assets/{asset_id}", routes)


class CosErrorMappingTests(unittest.TestCase):
    def test_explicit_cos_404_maps_to_not_found(self) -> None:
        client = FakeCosClient()
        client.errors[published_catalog_key()] = CosServiceError(
            "GET",
            {"code": "NoSuchKey", "message": "missing", "resource": "x", "requestid": "", "traceid": ""},
            404,
        )
        store = CosStore(client=client, bucket="example-bucket")
        with self.assertRaises(NotFound):
            store.catalog()
        response = _client(store).get("/v1/walls")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("NoSuchKey", response.text)

    def test_cos_auth_failure_does_not_map_to_404(self) -> None:
        client = FakeCosClient()
        client.errors[published_catalog_key()] = CosServiceError(
            "GET",
            {"code": "AccessDenied", "message": "denied", "resource": "x", "requestid": "", "traceid": ""},
            403,
        )
        store = CosStore(client=client, bucket="example-bucket")
        with self.assertRaises(StorageFailure):
            store.catalog()
        response = _client(store).get("/v1/walls")
        self.assertEqual(response.status_code, 502)
        self.assertNotEqual(response.status_code, 404)
        self.assertNotIn("AccessDenied", response.text)
        self.assertNotIn("denied", response.text.lower())

    def test_cos_network_failure_does_not_map_to_404(self) -> None:
        client = FakeCosClient()
        client.errors[published_catalog_key()] = CosClientError("timeout")
        store = CosStore(client=client, bucket="example-bucket")
        with self.assertRaises(StorageFailure):
            store.catalog()
        response = _client(store).get("/v1/walls")
        self.assertEqual(response.status_code, 502)
        self.assertNotEqual(response.status_code, 404)
        self.assertNotIn("timeout", response.text)

    def test_invalid_published_json_maps_to_500_not_404(self) -> None:
        client = _cos_example_client()
        client.objects[published_catalog_key()] = b"not-json"
        store = CosStore(client=client, bucket="example-bucket")
        with self.assertRaises(ContractError):
            store.catalog()
        response = _client(store).get("/v1/walls")
        self.assertEqual(response.status_code, 500)
        self.assertNotEqual(response.status_code, 404)

    def test_missing_cos_configuration_is_unavailable(self) -> None:
        saved = {
            name: os.environ.pop(name, None)
            for name in (
                "TENCENT_COS_REGION",
                "TENCENT_SECRET_ID",
                "TENCENT_SECRET_KEY",
                "TENCENT_COS_BUCKET",
            )
        }
        try:
            with self.assertRaises(StorageUnavailable):
                CosStore.from_env()
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_cos_asset_lookup_does_not_follow_latest_release(self) -> None:
        client = _cos_example_client()
        client.objects[published_catalog_key()] = json.dumps(
            example_catalog(latest_release_id=EXAMPLE_RELEASE_ID_2)
        ).encode("utf-8")
        client.objects[published_manifest_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID_2)] = json.dumps(
            example_manifest(release_id=EXAMPLE_RELEASE_ID_2, payload=EXAMPLE_ASSET_BYTES_V2)
        ).encode("utf-8")
        client.objects[published_asset_key(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID_2, EXAMPLE_ASSET_ID)] = (
            EXAMPLE_ASSET_BYTES_V2
        )
        store = CosStore(client=client, bucket="example-bucket")
        self.assertEqual(store.manifest(EXAMPLE_WALL_ID)["releaseId"], EXAMPLE_RELEASE_ID_2)
        self.assertEqual(
            store.asset_bytes(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID, EXAMPLE_ASSET_ID),
            EXAMPLE_ASSET_BYTES,
        )


if __name__ == "__main__":
    unittest.main()
