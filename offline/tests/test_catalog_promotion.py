"""Fake-store catalog promotion v1 tests. No real Tencent credentials or network."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.catalog_promotion.catalog import CATALOG_SCHEMA, encode_catalog
from offline.catalog_promotion.cli import run_promote_localization_release
from offline.catalog_promotion.pipeline import promote_localization_release
from offline.catalog_promotion.schema import PromotionState, ReasonCode
from offline.localization_package.schema import TYPE_DESCRIPTORS, TYPE_LANDMARKS, TYPE_S_WALL_COLMAP
from offline.publisher.fake_store import FakeObjectStore
from offline.publisher.keys import CATALOG_KEY, published_asset_key, published_manifest_key
from offline.publisher.store import ConcurrentModification, PublisherStoreError
from offline.publisher.tencent_promotion_store import TencentPromotionStore
from offline.publisher.tencent_store import TencentPublisherStore

WALL = "wall_promo_contract_01"
RELEASE = "r000007"
FORWARD = "r000008"
OLDER = "r000004"
NAME = "Promotion Contract Wall"
OTHER_WALL = "wall_unrelated_01"
OTHER_NAME = "Unrelated Wall"
OTHER_RELEASE = "r000003"
PROMOTION_DIR = ROOT / "offline" / "catalog_promotion"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _blobs() -> dict[str, bytes]:
    return {
        "stage3-descriptors": b"RVS1-synthetic-descriptors",
        "stage3-landmarks": b'{"landmarks":[]}\n',
        "s-wall-colmap": b'{"status":"VALIDATED"}\n',
    }


def _types() -> dict[str, str]:
    return {
        "stage3-descriptors": TYPE_DESCRIPTORS,
        "stage3-landmarks": TYPE_LANDMARKS,
        "s-wall-colmap": TYPE_S_WALL_COLMAP,
    }


def _asset_entries(blobs: dict[str, bytes] | None = None, *, required: bool = True) -> list[dict]:
    blobs = blobs or _blobs()
    types = _types()
    return [
        {
            "assetId": asset_id,
            "type": types[asset_id],
            "required": required,
            "sha256": _sha(data),
            "bytes": len(data),
        }
        for asset_id, data in blobs.items()
    ]


def _manifest_bytes(
    wall_id: str,
    release_id: str,
    assets: list[dict] | None = None,
) -> bytes:
    payload = {
        "schema": "cragpal.wall-manifest.v1",
        "wallId": wall_id,
        "releaseId": release_id,
        "createdAt": "2026-09-04T00:00:00Z",
        "assets": assets if assets is not None else _asset_entries(),
    }
    return json.dumps(payload, indent=2).encode("utf-8") + b"\n"


def seed_release(store: FakeObjectStore, wall_id: str = WALL, release_id: str = RELEASE) -> dict[str, bytes]:
    blobs = _blobs()
    store.objects[published_manifest_key(wall_id, release_id)] = _manifest_bytes(wall_id, release_id)
    for asset_id, data in blobs.items():
        store.objects[published_asset_key(wall_id, release_id, asset_id)] = data
    return blobs


def seed_catalog(store: FakeObjectStore, walls: list[dict]) -> bytes:
    payload = {"schema": CATALOG_SCHEMA, "walls": walls}
    data = encode_catalog(payload)
    store.objects[CATALOG_KEY] = data
    store.etags[CATALOG_KEY] = FakeObjectStore._etag_for(data)
    return data


def _promote(store: FakeObjectStore | None, **kwargs):
    params = {
        "wall_id": WALL,
        "release_id": RELEASE,
        "name": NAME,
        "approve": True,
        "store": store,
    }
    params.update(kwargs)
    return promote_localization_release(**params)


class _ConcurrentStore(FakeObjectStore):
    def __init__(self, replacement: bytes) -> None:
        super().__init__()
        self._replacement = replacement

    def put_if_match(self, key: str, data: bytes, *, expected_etag: str | None) -> None:
        self.mutate(key, self._replacement)
        return super().put_if_match(key, data, expected_etag=expected_etag)


class CatalogPromotionFakeStoreTests(unittest.TestCase):
    def test_01_missing_approval_zero_remote_calls(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        result = _promote(store, approve=False)
        self.assertEqual(result.state, PromotionState.PROMOTION_NOT_AUTHORIZED.value)
        self.assertEqual(result.reason_code, ReasonCode.PROMOTION_NOT_AUTHORIZED.value)
        self.assertFalse(result.promotion_approved)
        self.assertFalse(result.catalog_discoverable)
        self.assertEqual(store.calls, [])
        self.assertEqual(store.puts, [])
        self.assertEqual(result.puts, [])

    def test_02_manifest_missing(self) -> None:
        store = FakeObjectStore()
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.REMOTE_RELEASE_INVALID.value)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_MANIFEST_MISSING.value)
        self.assertEqual(store.puts, [])
        self.assertFalse(result.remote_release_validated)

    def test_03_manifest_malformed(self) -> None:
        store = FakeObjectStore()
        store.objects[published_manifest_key(WALL, RELEASE)] = b"{not-json"
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.REMOTE_RELEASE_INVALID.value)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_MANIFEST_INVALID.value)
        self.assertEqual(store.puts, [])

    def test_04_manifest_wall_id_mismatch(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        store.objects[published_manifest_key(WALL, RELEASE)] = _manifest_bytes("wall_other_01", RELEASE)
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_MANIFEST_WALL_ID_MISMATCH.value)
        self.assertEqual(store.puts, [])

    def test_05_manifest_release_id_mismatch(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        store.objects[published_manifest_key(WALL, RELEASE)] = _manifest_bytes(WALL, FORWARD)
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_MANIFEST_RELEASE_ID_MISMATCH.value)
        self.assertEqual(store.puts, [])

    def test_06_descriptors_missing(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        del store.objects[published_asset_key(WALL, RELEASE, "stage3-descriptors")]
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_DESCRIPTORS_MISSING.value)
        self.assertEqual(store.puts, [])

    def test_07_landmarks_missing(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        del store.objects[published_asset_key(WALL, RELEASE, "stage3-landmarks")]
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_LANDMARKS_MISSING.value)
        self.assertEqual(store.puts, [])

    def test_08_sim3_missing(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        del store.objects[published_asset_key(WALL, RELEASE, "s-wall-colmap")]
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_SIM3_MISSING.value)
        self.assertEqual(store.puts, [])

    def test_09_duplicate_semantic_asset_type(self) -> None:
        store = FakeObjectStore()
        blobs = _blobs()
        assets = _asset_entries(blobs)
        assets.append(dict(assets[0], assetId="stage3-descriptors-dup"))
        store.objects[published_manifest_key(WALL, RELEASE)] = _manifest_bytes(WALL, RELEASE, assets)
        for asset_id, data in blobs.items():
            store.objects[published_asset_key(WALL, RELEASE, asset_id)] = data
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_DUPLICATE_SEMANTIC_TYPE.value)
        self.assertEqual(store.puts, [])

    def test_10_required_localization_asset_required_false(self) -> None:
        store = FakeObjectStore()
        blobs = _blobs()
        store.objects[published_manifest_key(WALL, RELEASE)] = _manifest_bytes(
            WALL, RELEASE, _asset_entries(blobs, required=False)
        )
        for asset_id, data in blobs.items():
            store.objects[published_asset_key(WALL, RELEASE, asset_id)] = data
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_ASSET_NOT_REQUIRED.value)
        self.assertEqual(store.puts, [])

    def test_11_asset_bytes_mismatch(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        key = published_asset_key(WALL, RELEASE, "stage3-descriptors")
        store.objects[key] = store.objects[key] + b"x"
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_ASSET_BYTES_MISMATCH.value)
        self.assertEqual(store.puts, [])

    def test_12_asset_sha_mismatch(self) -> None:
        store = FakeObjectStore()
        blobs = seed_release(store)
        original = blobs["stage3-descriptors"]
        key = published_asset_key(WALL, RELEASE, "stage3-descriptors")
        store.objects[key] = b"X" * len(original)
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_ASSET_SHA_MISMATCH.value)
        self.assertEqual(store.puts, [])

    def test_13_malformed_catalog(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        store.objects[CATALOG_KEY] = b"{not-catalog"
        store.etags[CATALOG_KEY] = FakeObjectStore._etag_for(store.objects[CATALOG_KEY])
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.CATALOG_INVALID.value)
        self.assertEqual(result.reason_code, ReasonCode.CATALOG_INVALID.value)
        self.assertEqual(store.conditional_puts, [])
        self.assertTrue(result.remote_release_validated)

    def test_14_unsupported_catalog_schema(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        store.objects[CATALOG_KEY] = json.dumps({"schema": "cragpal.wall-catalog.v2", "walls": []}).encode()
        store.etags[CATALOG_KEY] = FakeObjectStore._etag_for(store.objects[CATALOG_KEY])
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.CATALOG_SCHEMA_UNSUPPORTED.value)
        self.assertEqual(store.conditional_puts, [])

    def test_15_duplicate_wall_id_already_present(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        entry = {"wallId": WALL, "name": NAME, "latestReleaseId": RELEASE}
        seed_catalog(store, [entry, dict(entry)])
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.CATALOG_INVALID.value)
        self.assertEqual(result.reason_code, ReasonCode.CATALOG_INVALID.value)
        self.assertEqual(store.conditional_puts, [])

    def test_16_existing_wall_name_conflict(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        before = seed_catalog(store, [{"wallId": WALL, "name": "Other Name", "latestReleaseId": OLDER}])
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.CATALOG_NAME_CONFLICT.value)
        self.assertEqual(result.reason_code, ReasonCode.CATALOG_NAME_CONFLICT.value)
        self.assertEqual(store.objects[CATALOG_KEY], before)
        self.assertEqual(store.conditional_puts, [])

    def test_17_release_regression(self) -> None:
        store = FakeObjectStore()
        seed_release(store, release_id=OLDER)
        before = seed_catalog(store, [{"wallId": WALL, "name": NAME, "latestReleaseId": RELEASE}])
        result = _promote(store, release_id=OLDER)
        self.assertEqual(result.state, PromotionState.CATALOG_RELEASE_REGRESSION.value)
        self.assertEqual(result.reason_code, ReasonCode.CATALOG_RELEASE_REGRESSION.value)
        self.assertEqual(store.objects[CATALOG_KEY], before)
        self.assertEqual(store.conditional_puts, [])

    def test_18_identical_already_promoted_zero_puts(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        before = seed_catalog(store, [{"wallId": WALL, "name": NAME, "latestReleaseId": RELEASE}])
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.ALREADY_CATALOG_DISCOVERABLE.value)
        self.assertTrue(result.catalog_discoverable)
        self.assertTrue(result.remote_release_validated)
        self.assertEqual(result.puts, [])
        self.assertEqual(store.conditional_puts, [])
        self.assertEqual(store.objects[CATALOG_KEY], before)

    def test_19_forward_release_promotion(self) -> None:
        store = FakeObjectStore()
        seed_release(store, release_id=FORWARD)
        seed_catalog(
            store,
            [
                {"wallId": OTHER_WALL, "name": OTHER_NAME, "latestReleaseId": OTHER_RELEASE},
                {"wallId": WALL, "name": NAME, "latestReleaseId": RELEASE},
            ],
        )
        result = _promote(store, release_id=FORWARD)
        self.assertEqual(result.state, PromotionState.CATALOG_DISCOVERABLE.value)
        self.assertEqual(result.puts, [CATALOG_KEY])
        self.assertEqual(store.conditional_puts, [CATALOG_KEY])
        catalog = json.loads(store.objects[CATALOG_KEY].decode("utf-8"))
        self.assertEqual(catalog["schema"], CATALOG_SCHEMA)
        by_id = {item["wallId"]: item for item in catalog["walls"]}
        self.assertEqual(by_id[WALL]["latestReleaseId"], FORWARD)
        self.assertEqual(by_id[WALL]["name"], NAME)
        self.assertEqual(by_id[OTHER_WALL], {"wallId": OTHER_WALL, "name": OTHER_NAME, "latestReleaseId": OTHER_RELEASE})

    def test_20_unrelated_catalog_entries_preserved_on_new_wall(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        extra = {"wallId": OTHER_WALL, "name": OTHER_NAME, "latestReleaseId": OTHER_RELEASE, "note": "keep-me"}
        seed_catalog(store, [extra])
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.CATALOG_DISCOVERABLE.value)
        catalog = json.loads(store.objects[CATALOG_KEY].decode("utf-8"))
        others = [item for item in catalog["walls"] if item["wallId"] != WALL]
        self.assertEqual(others, [extra])
        targets = [item for item in catalog["walls"] if item["wallId"] == WALL]
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["name"], NAME)
        self.assertEqual(targets[0]["latestReleaseId"], RELEASE)
        self.assertEqual(result.puts, [CATALOG_KEY])
        self.assertNotIn(published_manifest_key(WALL, RELEASE), store.puts)

    def test_21_simulated_concurrent_catalog_modification(self) -> None:
        replacement = encode_catalog(
            {"schema": CATALOG_SCHEMA, "walls": [{"wallId": OTHER_WALL, "name": OTHER_NAME, "latestReleaseId": OTHER_RELEASE}]}
        )
        store = _ConcurrentStore(replacement)
        seed_release(store)
        original = seed_catalog(store, [{"wallId": "wall_prior_01", "name": "Prior", "latestReleaseId": "r000001"}])
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.CATALOG_CONCURRENT_MODIFICATION.value)
        self.assertEqual(result.reason_code, ReasonCode.CATALOG_CONCURRENT_MODIFICATION.value)
        self.assertEqual(result.puts, [])
        self.assertEqual(store.objects[CATALOG_KEY], replacement)
        self.assertNotEqual(store.objects[CATALOG_KEY], original)

    def test_22_conditional_write_precondition_failure(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        before = seed_catalog(store, [{"wallId": OTHER_WALL, "name": OTHER_NAME, "latestReleaseId": OTHER_RELEASE}])
        store.precondition_failures.add(CATALOG_KEY)
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.CATALOG_CONCURRENT_MODIFICATION.value)
        self.assertEqual(result.reason_code, ReasonCode.CATALOG_CONCURRENT_MODIFICATION.value)
        self.assertEqual(result.puts, [])
        self.assertEqual(store.objects[CATALOG_KEY], before)

    def test_23_post_write_remote_catalog_mismatch(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        store.corrupt_after_put.add(CATALOG_KEY)
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.CATALOG_VERIFY_FAILED.value)
        self.assertEqual(result.reason_code, ReasonCode.CATALOG_VERIFY_FAILED.value)
        self.assertFalse(result.catalog_discoverable)

    def test_new_wall_on_missing_catalog_uses_if_none_match(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.CATALOG_DISCOVERABLE.value)
        self.assertEqual(result.puts, [CATALOG_KEY])
        catalog = json.loads(store.objects[CATALOG_KEY].decode("utf-8"))
        self.assertEqual(catalog["walls"], [{"wallId": WALL, "name": NAME, "latestReleaseId": RELEASE}])

    def test_manifest_missing_required_type_is_rejected(self) -> None:
        store = FakeObjectStore()
        assets = [item for item in _asset_entries() if item["type"] != TYPE_DESCRIPTORS]
        store.objects[published_manifest_key(WALL, RELEASE)] = _manifest_bytes(WALL, RELEASE, assets)
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_DESCRIPTORS_MISSING.value)
        self.assertEqual(store.puts, [])

    def test_release_ordinal_is_numeric_not_lexicographic(self) -> None:
        store = FakeObjectStore()
        seed_release(store, release_id="r000010")
        seed_catalog(store, [{"wallId": WALL, "name": NAME, "latestReleaseId": "r000009"}])
        result = _promote(store, release_id="r000010")
        self.assertEqual(result.state, PromotionState.CATALOG_DISCOVERABLE.value)
        catalog = json.loads(store.objects[CATALOG_KEY].decode("utf-8"))
        self.assertEqual(catalog["walls"][0]["latestReleaseId"], "r000010")

    def test_conditional_put_is_catalog_only(self) -> None:
        store = FakeObjectStore()
        with self.assertRaises(PublisherStoreError):
            store.put_if_match(published_manifest_key(WALL, RELEASE), b"{}", expected_etag=None)

    def test_publisher_adapter_still_cannot_touch_catalog(self) -> None:
        class _Client:
            def get_object(self, **kwargs):
                raise AssertionError("catalog must not reach publisher client")

            def put_object(self, **kwargs):
                raise AssertionError("catalog must not reach publisher client")

        adapter = TencentPublisherStore(client=_Client(), bucket="unused")
        with self.assertRaises(Exception):
            adapter.get_bytes(CATALOG_KEY)
        with self.assertRaises(Exception):
            adapter.put_bytes(CATALOG_KEY, b"{}")
        self.assertFalse(hasattr(adapter, "put_if_match"))

    def test_tencent_adapter_sends_if_match_and_maps_412(self) -> None:
        captured: dict[str, object] = {}

        class _Body:
            def get_raw_stream(self):
                return io.BytesIO(b'{"schema":"cragpal.wall-catalog.v1","walls":[]}')

        class _Client:
            def get_object(self, **kwargs):
                return {"Body": _Body(), "ETag": '"abc"'}

            def put_object(self, **kwargs):
                captured.update(kwargs)
                exc = Exception("precondition")
                exc.get_status_code = lambda: 412  # type: ignore[attr-defined]
                exc.get_error_code = lambda: "PreconditionFailed"  # type: ignore[attr-defined]
                raise exc

        adapter = TencentPromotionStore(client=_Client(), bucket="bucket")
        current = adapter.get_conditional(CATALOG_KEY)
        assert current is not None
        self.assertEqual(current.etag, '"abc"')
        with self.assertRaises(ConcurrentModification):
            adapter.put_if_match(CATALOG_KEY, b"{}", expected_etag='"abc"')
        self.assertEqual(captured["IfMatch"], '"abc"')
        self.assertNotIn("IfNoneMatch", captured)
        with self.assertRaises(PublisherStoreError):
            adapter.put_if_match(published_manifest_key(WALL, RELEASE), b"{}", expected_etag='"abc"')

    def test_tencent_adapter_create_if_absent_sends_if_none_match(self) -> None:
        captured: dict[str, object] = {}

        class _Client:
            def put_object(self, **kwargs):
                captured.update(kwargs)

        adapter = TencentPromotionStore(client=_Client(), bucket="bucket")
        adapter.put_if_match(CATALOG_KEY, b"{}", expected_etag=None)
        self.assertEqual(captured["IfNoneMatch"], "*")
        self.assertNotIn("IfMatch", captured)

    def test_cli_without_approve_makes_zero_writes(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = run_promote_localization_release(WALL, RELEASE, name=NAME, approve=False, store=store)
        self.assertEqual(code, 1)
        self.assertEqual(store.calls, [])
        self.assertIn("PROMOTION_NOT_AUTHORIZED", buf.getvalue())

    def test_cli_success_and_idempotent_rerun(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            first = run_promote_localization_release(WALL, RELEASE, name=NAME, approve=True, store=store)
        self.assertEqual(first, 0)
        self.assertEqual(store.conditional_puts, [CATALOG_KEY])
        with patch("sys.stdout", io.StringIO()):
            second = run_promote_localization_release(WALL, RELEASE, name=NAME, approve=True, store=store)
        self.assertEqual(second, 0)
        self.assertEqual(store.conditional_puts, [CATALOG_KEY])

    def test_rockvision_cli_requires_name_and_approve(self) -> None:
        spec = importlib.util.spec_from_file_location("rockvision_tools_cli_promo", ROOT / "tools" / "rockvision.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        tmp = Path(tempfile.mkdtemp())
        with patch("offline.catalog_promotion.cli.run_promote_localization_release", return_value=1) as fn:
            code = mod.main(
                ["promote-localization-release", WALL, RELEASE, "--name", NAME],
                root=tmp,
            )
        self.assertEqual(code, 1)
        self.assertFalse(fn.call_args.kwargs.get("approve"))
        self.assertEqual(fn.call_args.kwargs.get("name"), NAME)
        with patch("offline.catalog_promotion.cli.run_promote_localization_release", return_value=0) as fn:
            code = mod.main(
                ["promote-localization-release", WALL, RELEASE, "--name", NAME, "--approve"],
                root=tmp,
            )
        self.assertEqual(code, 0)
        self.assertTrue(fn.call_args.kwargs.get("approve"))

    def test_promotion_sources_have_no_delete_or_list(self) -> None:
        for path in sorted(PROMOTION_DIR.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("delete_object", text)
            self.assertNotIn("delete_objects", text)
            self.assertNotIn("list_objects", text)
        promo_store = (ROOT / "offline" / "publisher" / "tencent_promotion_store.py").read_text(encoding="utf-8")
        self.assertIn("IfMatch", promo_store)
        self.assertIn("IfNoneMatch", promo_store)
        self.assertNotIn("delete_object", promo_store)
        self.assertTrue(inspect.isclass(TencentPromotionStore))

    def test_does_not_target_real_synthetic_wall(self) -> None:
        sources = "\n".join(path.read_text(encoding="utf-8") for path in PROMOTION_DIR.glob("*.py"))
        self.assertNotIn("wall_publisher_e2e_01", sources)


if __name__ == "__main__":
    unittest.main()
