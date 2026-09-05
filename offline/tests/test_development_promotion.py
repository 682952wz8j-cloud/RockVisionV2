"""Fake-store development_test promotion tests. No real Tencent credentials or network."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from offline.catalog_promotion.cli import run_promote_localization_release
from offline.catalog_promotion.development_cli import run_promote_development_test_release
from offline.catalog_promotion.development_promotion import (
    DEVELOPMENT_REQUIRED_ASSET_TYPES,
    DEVELOPMENT_TEST_ENVIRONMENT,
    DEVELOPMENT_TEST_NOT_PRODUCTION_QUALIFIED,
    decode_development_cloud_manifest,
    promote_development_test_release,
)
from offline.catalog_promotion.pipeline import promote_localization_release
from offline.catalog_promotion.record import encode_promotion_record, promotion_identity, promotion_record
from offline.catalog_promotion.schema import PromotionState, ReasonCode
from offline.localization_package.schema import (
    ENVIRONMENT_PRODUCTION,
    TYPE_DESCRIPTORS,
    TYPE_LANDMARKS,
    TYPE_S_WALL_COLMAP,
)
from offline.publisher.fake_store import FakeObjectStore
from offline.publisher.keys import (
    CATALOG_KEY,
    published_asset_key,
    published_manifest_key,
    published_promotion_key,
)

PROMOTION_DIR = ROOT / "offline" / "catalog_promotion"
WALL = "wall_jiulongfeng_01_dev"
RELEASE = "r000001"
NAME = "Jiulongfeng Development Wall"
WHEN = "2026-09-05T00:00:00Z"
LATER = "2026-09-05T12:00:00Z"
EMBEDDED_LANDMARK_WALL = "wall_jiulongfeng_01"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _descriptor_bytes() -> bytes:
    return b"RVS1-jiulongfeng-dev-fixture"


def _landmark_bytes() -> bytes:
    return (
        json.dumps(
            {
                "schema": 1,
                "wallId": EMBEDDED_LANDMARK_WALL,
                "developmentFixtureOnly": True,
                "notAWallPackage": True,
                "landmarks": [],
            },
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _blobs() -> dict[str, bytes]:
    return {
        "stage3-descriptors": _descriptor_bytes(),
        "stage3-landmarks": _landmark_bytes(),
    }


def _asset_entries(blobs: dict[str, bytes] | None = None, extra: list[dict] | None = None) -> list[dict]:
    blobs = blobs or _blobs()
    types = {
        "stage3-descriptors": TYPE_DESCRIPTORS,
        "stage3-landmarks": TYPE_LANDMARKS,
    }
    assets = [
        {
            "assetId": asset_id,
            "type": types[asset_id],
            "required": True,
            "sha256": _sha(data),
            "bytes": len(data),
        }
        for asset_id, data in blobs.items()
    ]
    if extra:
        assets.extend(extra)
    return assets


def _manifest_bytes(
    wall_id: str = WALL,
    release_id: str = RELEASE,
    assets: list[dict] | None = None,
) -> bytes:
    payload = {
        "schema": "cragpal.wall-manifest.v1",
        "wallId": wall_id,
        "releaseId": release_id,
        "createdAt": "2026-09-03T13:56:27Z",
        "assets": assets if assets is not None else _asset_entries(),
    }
    return json.dumps(payload, indent=2).encode("utf-8") + b"\n"


def seed_development_release(
    store: FakeObjectStore,
    *,
    wall_id: str = WALL,
    release_id: str = RELEASE,
    blobs: dict[str, bytes] | None = None,
    extra_assets: list[tuple[str, bytes, dict]] | None = None,
) -> bytes:
    blobs = dict(blobs or _blobs())
    extra_entries: list[dict] = []
    extra_blobs: dict[str, bytes] = {}
    if extra_assets:
        for asset_id, data, meta in extra_assets:
            extra_blobs[asset_id] = data
            extra_entries.append(meta)
    manifest = _manifest_bytes(wall_id, release_id, _asset_entries(blobs, extra=extra_entries or None))
    store.objects[published_manifest_key(wall_id, release_id)] = manifest
    for asset_id, data in {**blobs, **extra_blobs}.items():
        store.objects[published_asset_key(wall_id, release_id, asset_id)] = data
    return manifest


def _promote(store: FakeObjectStore | None, **kwargs):
    params = {
        "wall_id": WALL,
        "release_id": RELEASE,
        "name": NAME,
        "approve": True,
        "store": store,
        "promoted_at": WHEN,
    }
    params.update(kwargs)
    return promote_development_test_release(**params)


class DevelopmentPromotionContractTests(unittest.TestCase):
    def test_01_valid_descriptors_landmarks_qualifies(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.PROMOTION_RECORD_CREATED.value)
        self.assertTrue(result.remote_release_validated)
        self.assertTrue(result.promotion_record_created)
        self.assertFalse(result.catalog_discoverable)

    def test_02_no_sim3_required_for_development_test(self) -> None:
        store = FakeObjectStore()
        manifest = json.loads(seed_development_release(store).decode("utf-8"))
        types = [item["type"] for item in manifest["assets"]]
        self.assertEqual(types, [TYPE_DESCRIPTORS, TYPE_LANDMARKS])
        self.assertNotIn(TYPE_S_WALL_COLMAP, types)
        self.assertNotIn(TYPE_S_WALL_COLMAP, DEVELOPMENT_REQUIRED_ASSET_TYPES)
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.PROMOTION_RECORD_CREATED.value)

    def test_03_production_promoter_still_rejects_missing_sim3(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        result = promote_localization_release(
            wall_id=WALL,
            release_id=RELEASE,
            name=NAME,
            approve=True,
            store=store,
            promoted_at=WHEN,
        )
        self.assertEqual(result.state, PromotionState.REMOTE_RELEASE_INVALID.value)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_SIM3_MISSING.value)
        self.assertEqual(store.absent_puts, [])
        self.assertNotIn(published_promotion_key(WALL, RELEASE), store.objects)

    def test_04_missing_descriptors_fails(self) -> None:
        store = FakeObjectStore()
        blobs = {"stage3-landmarks": _landmark_bytes()}
        assets = [
            {
                "assetId": "stage3-landmarks",
                "type": TYPE_LANDMARKS,
                "required": True,
                "sha256": _sha(blobs["stage3-landmarks"]),
                "bytes": len(blobs["stage3-landmarks"]),
            }
        ]
        store.objects[published_manifest_key(WALL, RELEASE)] = _manifest_bytes(assets=assets)
        store.objects[published_asset_key(WALL, RELEASE, "stage3-landmarks")] = blobs["stage3-landmarks"]
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_DESCRIPTORS_MISSING.value)
        self.assertEqual(store.puts, [])

    def test_05_missing_landmarks_fails(self) -> None:
        store = FakeObjectStore()
        blobs = {"stage3-descriptors": _descriptor_bytes()}
        assets = [
            {
                "assetId": "stage3-descriptors",
                "type": TYPE_DESCRIPTORS,
                "required": True,
                "sha256": _sha(blobs["stage3-descriptors"]),
                "bytes": len(blobs["stage3-descriptors"]),
            }
        ]
        store.objects[published_manifest_key(WALL, RELEASE)] = _manifest_bytes(assets=assets)
        store.objects[published_asset_key(WALL, RELEASE, "stage3-descriptors")] = blobs["stage3-descriptors"]
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_LANDMARKS_MISSING.value)
        self.assertEqual(store.puts, [])

    def test_06_duplicate_required_semantic_type_fails(self) -> None:
        store = FakeObjectStore()
        blobs = _blobs()
        assets = _asset_entries(blobs) + [
            {
                "assetId": "stage3-descriptors-dup",
                "type": TYPE_DESCRIPTORS,
                "required": True,
                "sha256": _sha(blobs["stage3-descriptors"]),
                "bytes": len(blobs["stage3-descriptors"]),
            }
        ]
        store.objects[published_manifest_key(WALL, RELEASE)] = _manifest_bytes(assets=assets)
        for asset_id, data in blobs.items():
            store.objects[published_asset_key(WALL, RELEASE, asset_id)] = data
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_DUPLICATE_SEMANTIC_TYPE.value)
        self.assertEqual(store.puts, [])

    def test_07_required_asset_missing_remotely_fails(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        del store.objects[published_asset_key(WALL, RELEASE, "stage3-descriptors")]
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_DESCRIPTORS_MISSING.value)
        self.assertEqual(store.puts, [])

    def test_08_byte_mismatch_fails(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        key = published_asset_key(WALL, RELEASE, "stage3-descriptors")
        store.objects[key] = store.objects[key] + b"x"
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_ASSET_BYTES_MISMATCH.value)
        self.assertEqual(store.puts, [])

    def test_09_sha_mismatch_fails(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        original = _descriptor_bytes()
        store.objects[published_asset_key(WALL, RELEASE, "stage3-descriptors")] = b"X" * len(original)
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_ASSET_SHA_MISMATCH.value)
        self.assertEqual(store.puts, [])

    def test_10_wall_id_mismatch_fails(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        store.objects[published_manifest_key(WALL, RELEASE)] = _manifest_bytes("wall_other_01", RELEASE)
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_MANIFEST_WALL_ID_MISMATCH.value)
        self.assertEqual(store.puts, [])

    def test_11_release_id_mismatch_fails(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        store.objects[published_manifest_key(WALL, RELEASE)] = _manifest_bytes(WALL, "r000002")
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_MANIFEST_RELEASE_ID_MISMATCH.value)
        self.assertEqual(store.puts, [])

    def test_12_malformed_manifest_fails(self) -> None:
        store = FakeObjectStore()
        store.objects[published_manifest_key(WALL, RELEASE)] = b"{not-json"
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_MANIFEST_INVALID.value)
        self.assertEqual(store.puts, [])

    def test_13_first_promotion_creates_one_record(self) -> None:
        store = FakeObjectStore()
        catalog_before = b"legacy-catalog"
        store.objects[CATALOG_KEY] = catalog_before
        seed_development_release(store)
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.PROMOTION_RECORD_CREATED.value)
        key = published_promotion_key(WALL, RELEASE)
        self.assertEqual(result.puts, [key])
        self.assertEqual(store.absent_puts, [key])
        self.assertEqual(store.puts, [key])
        self.assertIn(key, store.objects)
        self.assertEqual(store.objects[CATALOG_KEY], catalog_before)

    def test_14_record_environment_is_development_test(self) -> None:
        store = FakeObjectStore()
        manifest = seed_development_release(store)
        result = _promote(store)
        payload = json.loads(store.objects[published_promotion_key(WALL, RELEASE)].decode("utf-8"))
        self.assertEqual(payload["schema"], "cragpal.wall-promotion.v1")
        self.assertEqual(payload["wallId"], WALL)
        self.assertEqual(payload["releaseId"], RELEASE)
        self.assertEqual(payload["name"], NAME)
        self.assertEqual(payload["environment"], DEVELOPMENT_TEST_ENVIRONMENT)
        self.assertEqual(payload["releaseManifestSha256"], _sha(manifest))
        self.assertEqual(result.state, PromotionState.PROMOTION_RECORD_CREATED.value)

    def test_15_environment_participates_in_identity(self) -> None:
        store = FakeObjectStore()
        manifest = seed_development_release(store)
        _promote(store)
        payload = json.loads(store.objects[published_promotion_key(WALL, RELEASE)].decode("utf-8"))
        production = promotion_record(
            wall_id=WALL,
            release_id=RELEASE,
            name=NAME,
            promoted_at=WHEN,
            release_manifest_sha256=_sha(manifest),
            environment=ENVIRONMENT_PRODUCTION,
        )
        self.assertEqual(promotion_identity(payload)[5], DEVELOPMENT_TEST_ENVIRONMENT)
        self.assertNotEqual(promotion_identity(payload), promotion_identity(production))

    def test_16_identical_retry_idempotent_zero_new_write(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        first = _promote(store, promoted_at=WHEN)
        before = store.objects[published_promotion_key(WALL, RELEASE)]
        second = _promote(store, promoted_at=LATER)
        self.assertEqual(first.state, PromotionState.PROMOTION_RECORD_CREATED.value)
        self.assertEqual(second.state, PromotionState.ALREADY_PROMOTED_IDENTICAL.value)
        self.assertEqual(store.absent_puts, [published_promotion_key(WALL, RELEASE)])
        self.assertEqual(store.objects[published_promotion_key(WALL, RELEASE)], before)
        self.assertEqual(second.puts, [])

    def test_17_different_name_immutable_conflict(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        first = _promote(store)
        before = store.objects[published_promotion_key(WALL, RELEASE)]
        second = _promote(store, name="Other Name")
        self.assertEqual(first.state, PromotionState.PROMOTION_RECORD_CREATED.value)
        self.assertEqual(second.state, PromotionState.IMMUTABLE_PROMOTION_CONFLICT.value)
        self.assertEqual(second.reason_code, ReasonCode.IMMUTABLE_PROMOTION_CONFLICT.value)
        self.assertEqual(store.objects[published_promotion_key(WALL, RELEASE)], before)
        self.assertEqual(store.absent_puts, [published_promotion_key(WALL, RELEASE)])

    def test_18_production_candidate_is_not_development_identity(self) -> None:
        dev = promotion_record(
            wall_id=WALL,
            release_id=RELEASE,
            name=NAME,
            promoted_at=WHEN,
            release_manifest_sha256="a" * 64,
            environment=DEVELOPMENT_TEST_ENVIRONMENT,
        )
        production = promotion_record(
            wall_id=WALL,
            release_id=RELEASE,
            name=NAME,
            promoted_at=WHEN,
            release_manifest_sha256="a" * 64,
            environment=ENVIRONMENT_PRODUCTION,
        )
        self.assertNotEqual(promotion_identity(dev), promotion_identity(production))
        self.assertEqual(dev["environment"], DEVELOPMENT_TEST_ENVIRONMENT)
        self.assertEqual(production["environment"], ENVIRONMENT_PRODUCTION)

    def test_19_malformed_existing_promotion_fails_closed(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        store.objects[published_promotion_key(WALL, RELEASE)] = b"{not-json"
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.IMMUTABLE_PROMOTION_CONFLICT.value)
        self.assertEqual(store.absent_puts, [])
        self.assertEqual(store.objects[published_promotion_key(WALL, RELEASE)], b"{not-json")

    def test_20_no_catalog_write(self) -> None:
        store = FakeObjectStore()
        catalog_before = b"legacy-catalog"
        store.objects[CATALOG_KEY] = catalog_before
        seed_development_release(store)
        _promote(store)
        self.assertEqual(store.objects[CATALOG_KEY], catalog_before)
        self.assertNotIn(CATALOG_KEY, store.puts)
        self.assertNotIn(CATALOG_KEY, store.absent_puts)

    def test_21_no_release_asset_write(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        before = {
            key: value
            for key, value in store.objects.items()
            if "/assets/" in key
        }
        _promote(store)
        after = {
            key: value
            for key, value in store.objects.items()
            if "/assets/" in key
        }
        self.assertEqual(before, after)
        self.assertFalse(any("/assets/" in key for key in store.puts))
        self.assertFalse(any("/assets/" in key for key in store.absent_puts))

    def test_22_no_release_manifest_write(self) -> None:
        store = FakeObjectStore()
        manifest = seed_development_release(store)
        key = published_manifest_key(WALL, RELEASE)
        _promote(store)
        self.assertEqual(store.objects[key], manifest)
        self.assertNotIn(key, store.puts)
        self.assertNotIn(key, store.absent_puts)

    def test_23_no_delete_object(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        _promote(store)
        self.assertFalse(any(call[0].upper().startswith("DELETE") for call in store.calls))
        self.assertFalse(hasattr(store, "delete_object") and callable(getattr(store, "delete_object")))
        source = (PROMOTION_DIR / "development_promotion.py").read_text(encoding="utf-8")
        self.assertNotIn("delete_object", source)
        self.assertNotIn("DeleteObject", source)

    def test_24_explicit_approval_required(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        result = _promote(store, approve=False)
        self.assertEqual(result.state, PromotionState.PROMOTION_NOT_AUTHORIZED.value)
        self.assertEqual(result.reason_code, ReasonCode.PROMOTION_NOT_AUTHORIZED.value)
        self.assertFalse(result.promotion_approved)
        self.assertEqual(store.calls, [])
        self.assertEqual(store.puts, [])

    def test_25_production_cli_unchanged(self) -> None:
        cli = (PROMOTION_DIR / "cli.py").read_text(encoding="utf-8")
        self.assertIn("promote_localization_release", cli)
        self.assertNotIn("promote_development_test_release", cli)
        self.assertNotIn("allow-dev", cli)
        self.assertNotIn("ENVIRONMENT_DEVELOPMENT_TEST", cli)
        self.assertIn("environment: production", cli)

    def test_26_development_package_not_publishable_unchanged(self) -> None:
        publisher = (ROOT / "offline" / "publisher" / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn("DEVELOPMENT_PACKAGE_NOT_PUBLISHABLE", publisher)
        self.assertIn("ENVIRONMENT_DEVELOPMENT_TEST", publisher)

    def test_27_production_promoter_still_requires_sim3(self) -> None:
        pipeline = (PROMOTION_DIR / "pipeline.py").read_text(encoding="utf-8")
        self.assertIn("TYPE_S_WALL_COLMAP", pipeline)
        self.assertIn("REMOTE_SIM3_MISSING", pipeline)
        self.assertIn("environment=ENVIRONMENT_PRODUCTION", pipeline)
        self.assertNotIn("ENVIRONMENT_DEVELOPMENT_TEST", pipeline)
        self.assertNotIn("allow-dev", pipeline)
        self.assertNotIn("promote_development_test_release", pipeline)

    def test_28_no_allow_dev_bypass_exists(self) -> None:
        sources = "\n".join(path.read_text(encoding="utf-8") for path in PROMOTION_DIR.glob("*.py"))
        self.assertNotIn("allow-dev", sources)
        self.assertNotIn("skip-sim3", sources)
        self.assertNotIn("ignore-production-gates", sources)
        signature = inspect.signature(promote_development_test_release)
        self.assertNotIn("environment", signature.parameters)
        self.assertEqual(
            list(signature.parameters),
            ["wall_id", "release_id", "name", "approve", "store", "promoted_at"],
        )

    def test_29_jiulongfeng_quirks_do_not_create_production_claims(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        landmarks = json.loads(store.objects[published_asset_key(WALL, RELEASE, "stage3-landmarks")])
        self.assertTrue(landmarks["developmentFixtureOnly"])
        self.assertTrue(landmarks["notAWallPackage"])
        self.assertEqual(landmarks["wallId"], EMBEDDED_LANDMARK_WALL)
        self.assertNotEqual(landmarks["wallId"], WALL)
        result = _promote(store)
        payload = json.loads(store.objects[published_promotion_key(WALL, RELEASE)].decode("utf-8"))
        self.assertEqual(result.state, PromotionState.PROMOTION_RECORD_CREATED.value)
        self.assertEqual(payload["environment"], DEVELOPMENT_TEST_ENVIRONMENT)
        self.assertNotEqual(payload["environment"], ENVIRONMENT_PRODUCTION)
        self.assertTrue(DEVELOPMENT_TEST_NOT_PRODUCTION_QUALIFIED)
        self.assertFalse(result.catalog_discoverable)
        production = promote_localization_release(
            wall_id=WALL,
            release_id=RELEASE,
            name=NAME,
            approve=True,
            store=store,
            promoted_at=WHEN,
        )
        self.assertEqual(production.reason_code, ReasonCode.REMOTE_SIM3_MISSING.value)
        self.assertEqual(payload["environment"], DEVELOPMENT_TEST_ENVIRONMENT)

    def test_30_backend_debug_audience_accepts_dev_record_excludes_production(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.PROMOTION_RECORD_CREATED.value)
        payload = json.loads(store.objects[published_promotion_key(WALL, RELEASE)].decode("utf-8"))
        from app.catalog_projection import filter_catalog_for_audience, project_promotions
        from app.contract import AUDIENCE_DEBUG_TEST, AUDIENCE_PRODUCTION

        projected = project_promotions([payload])
        production = filter_catalog_for_audience(projected, AUDIENCE_PRODUCTION)
        debug = filter_catalog_for_audience(projected, AUDIENCE_DEBUG_TEST)
        self.assertEqual(production["walls"], [])
        self.assertEqual([item["wallId"] for item in debug["walls"]], [WALL])
        self.assertEqual(debug["walls"][0]["environment"], DEVELOPMENT_TEST_ENVIRONMENT)
        self.assertEqual(debug["walls"][0]["latestReleaseId"], RELEASE)
        self.assertEqual(debug["walls"][0]["name"], NAME)

    def test_optional_undeclared_sim3_is_not_fetched_as_required(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.PROMOTION_RECORD_CREATED.value)
        sim3_key = published_asset_key(WALL, RELEASE, "s-wall-colmap")
        self.assertNotIn(sim3_key, store.gets)

    def test_optional_extra_asset_may_be_absent(self) -> None:
        store = FakeObjectStore()
        extra = {
            "assetId": "optional-notes",
            "type": "development_notes",
            "required": False,
            "sha256": _sha(b"notes"),
            "bytes": 5,
        }
        seed_development_release(store, extra_assets=[("optional-notes", b"notes", extra)])
        del store.objects[published_asset_key(WALL, RELEASE, "optional-notes")]
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.PROMOTION_RECORD_CREATED.value)

    def test_extra_required_declared_asset_is_verified(self) -> None:
        store = FakeObjectStore()
        extra_bytes = b"extra-required"
        extra = {
            "assetId": "extra-required",
            "type": "development_extra",
            "required": True,
            "sha256": _sha(extra_bytes),
            "bytes": len(extra_bytes),
        }
        seed_development_release(store, extra_assets=[("extra-required", extra_bytes, extra)])
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.PROMOTION_RECORD_CREATED.value)
        del store.objects[published_promotion_key(WALL, RELEASE)]
        del store.objects[published_asset_key(WALL, RELEASE, "extra-required")]
        store.puts.clear()
        store.absent_puts.clear()
        missing = _promote(store)
        self.assertEqual(missing.reason_code, ReasonCode.REMOTE_ASSET_MISSING.value)
        self.assertEqual(store.absent_puts, [])

    def test_cli_without_approve_zero_writes(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = run_promote_development_test_release(WALL, RELEASE, name=NAME, approve=False, store=store)
        self.assertEqual(code, 1)
        self.assertEqual(store.calls, [])
        output = buf.getvalue()
        self.assertIn("PROMOTION_NOT_AUTHORIZED", output)
        self.assertIn("development_test", output)

    def test_cli_success_emits_development_test(self) -> None:
        store = FakeObjectStore()
        seed_development_release(store)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = run_promote_development_test_release(WALL, RELEASE, name=NAME, approve=True, store=store)
        self.assertEqual(code, 0)
        output = buf.getvalue()
        self.assertIn("environment: development_test", output)
        self.assertIn("NOT a production promotion", output)
        self.assertIn("PRODUCTION_QUALIFIED: NO", output)
        self.assertEqual(store.absent_puts, [published_promotion_key(WALL, RELEASE)])

    def test_rockvision_separate_development_command(self) -> None:
        spec = importlib.util.spec_from_file_location("rockvision_tools_cli_dev_promo", ROOT / "tools" / "rockvision.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        tmp = Path(tempfile.mkdtemp())
        with patch(
            "offline.catalog_promotion.development_cli.run_promote_development_test_release",
            return_value=1,
        ) as fn:
            code = mod.main(["promote-development-release", WALL, RELEASE, "--name", NAME], root=tmp)
        self.assertEqual(code, 1)
        self.assertFalse(fn.call_args.kwargs.get("approve"))
        with patch(
            "offline.catalog_promotion.development_cli.run_promote_development_test_release",
            return_value=0,
        ) as fn:
            code = mod.main(
                ["promote-development-release", WALL, RELEASE, "--name", NAME, "--approve"],
                root=tmp,
            )
        self.assertEqual(code, 0)
        self.assertTrue(fn.call_args.kwargs.get("approve"))
        with patch("offline.catalog_promotion.cli.run_promote_localization_release", return_value=0) as prod:
            code = mod.main(
                ["promote-localization-release", WALL, RELEASE, "--name", NAME, "--approve"],
                root=tmp,
            )
        self.assertEqual(code, 0)
        self.assertTrue(prod.called)

    def test_tencent_forbid_overwrite_path_preserved(self) -> None:
        promo_store = (ROOT / "offline" / "publisher" / "tencent_promotion_store.py").read_text(encoding="utf-8")
        self.assertIn('ForbidOverwrite="true"', promo_store)
        self.assertIn("x-cos-forbid-overwrite", promo_store)
        source = (PROMOTION_DIR / "development_promotion.py").read_text(encoding="utf-8")
        self.assertIn("put_if_absent", source)
        self.assertNotIn("put_bytes", source)

    def test_decode_rejects_empty_localization_assets(self) -> None:
        with self.assertRaises(Exception) as exc:
            decode_development_cloud_manifest(
                {
                    "schema": "cragpal.wall-manifest.v1",
                    "wallId": WALL,
                    "releaseId": RELEASE,
                    "createdAt": "2026-09-03T13:56:27Z",
                    "assets": [],
                },
                wall_id=WALL,
                release_id=RELEASE,
            )
        self.assertEqual(exc.exception.reason, ReasonCode.REMOTE_DESCRIPTORS_MISSING)


class DevelopmentPromotionSourceBoundaryTests(unittest.TestCase):
    def test_build_cannot_invoke_development_promotion(self) -> None:
        from offline.wall_build.orchestrator import FORBIDDEN_COMMANDS

        self.assertIn("promote-development-release", FORBIDDEN_COMMANDS)
        self.assertIn("promote-localization-release", FORBIDDEN_COMMANDS)

    def test_production_cli_does_not_overload_development(self) -> None:
        production_cli = inspect.getsource(run_promote_localization_release)
        self.assertNotIn("development_test", production_cli)
        self.assertNotIn("promote_development_test_release", production_cli)


if __name__ == "__main__":
    unittest.main()
