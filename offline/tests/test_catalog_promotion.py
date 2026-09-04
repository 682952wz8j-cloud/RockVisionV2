"""Fake-store immutable promotion-record tests. No real Tencent credentials or network."""

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

from offline.catalog_promotion.catalog import CATALOG_SCHEMA
from offline.catalog_promotion.cli import run_promote_localization_release
from offline.catalog_promotion.pipeline import promote_localization_release
from offline.catalog_promotion.projector import ProjectionError, project_catalog
from offline.catalog_promotion.record import encode_promotion_record, promotion_record
from offline.catalog_promotion.schema import PromotionState, ReasonCode
from offline.localization_package.schema import TYPE_DESCRIPTORS, TYPE_LANDMARKS, TYPE_S_WALL_COLMAP
from offline.publisher.fake_store import FakeObjectStore
from offline.publisher.keys import (
    CATALOG_KEY,
    published_asset_key,
    published_manifest_key,
    published_promotion_key,
)
from offline.publisher.store import ObjectAlreadyExists, PublisherStoreError
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
WHEN = "2026-09-04T15:00:00Z"
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


def _manifest_bytes(wall_id: str, release_id: str, assets: list[dict] | None = None) -> bytes:
    payload = {
        "schema": "cragpal.wall-manifest.v1",
        "wallId": wall_id,
        "releaseId": release_id,
        "createdAt": "2026-09-04T00:00:00Z",
        "assets": assets if assets is not None else _asset_entries(),
    }
    return json.dumps(payload, indent=2).encode("utf-8") + b"\n"


def seed_release(store: FakeObjectStore, wall_id: str = WALL, release_id: str = RELEASE) -> bytes:
    blobs = _blobs()
    manifest = _manifest_bytes(wall_id, release_id)
    store.objects[published_manifest_key(wall_id, release_id)] = manifest
    for asset_id, data in blobs.items():
        store.objects[published_asset_key(wall_id, release_id, asset_id)] = data
    return manifest


def seed_promotion(
    store: FakeObjectStore,
    *,
    wall_id: str,
    release_id: str,
    name: str,
    manifest_sha: str,
    promoted_at: str = WHEN,
) -> bytes:
    payload = promotion_record(
        wall_id=wall_id,
        release_id=release_id,
        name=name,
        promoted_at=promoted_at,
        release_manifest_sha256=manifest_sha,
    )
    data = encode_promotion_record(payload)
    store.objects[published_promotion_key(wall_id, release_id)] = data
    return data


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
    return promote_localization_release(**params)


class ImmutablePromotionFakeStoreTests(unittest.TestCase):
    def test_01_missing_approval_zero_writes(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        result = _promote(store, approve=False)
        self.assertEqual(result.state, PromotionState.PROMOTION_NOT_AUTHORIZED.value)
        self.assertEqual(result.reason_code, ReasonCode.PROMOTION_NOT_AUTHORIZED.value)
        self.assertFalse(result.promotion_approved)
        self.assertFalse(result.promotion_record_created)
        self.assertFalse(result.catalog_discoverable)
        self.assertEqual(store.calls, [])
        self.assertEqual(store.puts, [])

    def test_02_manifest_missing(self) -> None:
        store = FakeObjectStore()
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_MANIFEST_MISSING.value)
        self.assertEqual(store.puts, [])

    def test_03_manifest_malformed(self) -> None:
        store = FakeObjectStore()
        store.objects[published_manifest_key(WALL, RELEASE)] = b"{not-json"
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_MANIFEST_INVALID.value)
        self.assertEqual(store.puts, [])

    def test_04_wall_mismatch(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        store.objects[published_manifest_key(WALL, RELEASE)] = _manifest_bytes("wall_other_01", RELEASE)
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_MANIFEST_WALL_ID_MISMATCH.value)
        self.assertEqual(store.puts, [])

    def test_05_release_mismatch(self) -> None:
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

    def test_09_bad_asset_bytes(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        key = published_asset_key(WALL, RELEASE, "stage3-descriptors")
        store.objects[key] = store.objects[key] + b"x"
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_ASSET_BYTES_MISMATCH.value)
        self.assertEqual(store.puts, [])

    def test_10_bad_asset_sha(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        original = _blobs()["stage3-descriptors"]
        store.objects[published_asset_key(WALL, RELEASE, "stage3-descriptors")] = b"X" * len(original)
        result = _promote(store)
        self.assertEqual(result.reason_code, ReasonCode.REMOTE_ASSET_SHA_MISMATCH.value)
        self.assertEqual(store.puts, [])

    def test_11_missing_promotion_record_creates(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        catalog_before = b"legacy-catalog"
        store.objects[CATALOG_KEY] = catalog_before
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.PROMOTION_RECORD_CREATED.value)
        self.assertTrue(result.promotion_record_created)
        self.assertFalse(result.catalog_discoverable)
        key = published_promotion_key(WALL, RELEASE)
        self.assertEqual(result.puts, [key])
        self.assertIn(key, store.objects)
        self.assertEqual(store.objects[CATALOG_KEY], catalog_before)
        self.assertNotIn(CATALOG_KEY, store.puts)
        self.assertNotIn(CATALOG_KEY, store.gets)
        payload = json.loads(store.objects[key].decode("utf-8"))
        self.assertEqual(payload["schema"], "cragpal.wall-promotion.v1")
        self.assertEqual(payload["wallId"], WALL)
        self.assertEqual(payload["releaseId"], RELEASE)
        self.assertEqual(payload["name"], NAME)

    def test_12_identical_existing_promotion_idempotent(self) -> None:
        store = FakeObjectStore()
        manifest = seed_release(store)
        before = seed_promotion(store, wall_id=WALL, release_id=RELEASE, name=NAME, manifest_sha=_sha(manifest))
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.ALREADY_PROMOTED_IDENTICAL.value)
        self.assertTrue(result.promotion_record_created)
        self.assertEqual(result.puts, [])
        self.assertEqual(store.absent_puts, [])
        self.assertEqual(store.objects[published_promotion_key(WALL, RELEASE)], before)

    def test_13_differing_existing_promotion_conflict(self) -> None:
        store = FakeObjectStore()
        seed_release(store)
        before = seed_promotion(
            store,
            wall_id=WALL,
            release_id=RELEASE,
            name="Other Name",
            manifest_sha="0" * 64,
        )
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.IMMUTABLE_PROMOTION_CONFLICT.value)
        self.assertEqual(result.reason_code, ReasonCode.IMMUTABLE_PROMOTION_CONFLICT.value)
        self.assertEqual(store.objects[published_promotion_key(WALL, RELEASE)], before)
        self.assertEqual(store.absent_puts, [])

    def test_14_two_releases_highest_ordinal_projected(self) -> None:
        store = FakeObjectStore()
        older = seed_release(store, release_id=OLDER)
        newer = seed_release(store, release_id=FORWARD)
        self.assertEqual(_promote(store, release_id=OLDER).state, PromotionState.PROMOTION_RECORD_CREATED.value)
        self.assertEqual(_promote(store, release_id=FORWARD).state, PromotionState.PROMOTION_RECORD_CREATED.value)
        records = [
            json.loads(store.objects[published_promotion_key(WALL, OLDER)].decode("utf-8")),
            json.loads(store.objects[published_promotion_key(WALL, FORWARD)].decode("utf-8")),
        ]
        catalog = project_catalog(records)
        self.assertEqual(catalog["walls"][0]["latestReleaseId"], FORWARD)
        self.assertEqual(len(catalog["walls"]), 1)
        self.assertTrue(older and newer)

    def test_15_concurrent_different_releases_preserved(self) -> None:
        store = FakeObjectStore()
        seed_release(store, release_id=OLDER)
        seed_release(store, release_id=FORWARD)
        first = _promote(store, release_id=OLDER)
        second = _promote(store, release_id=FORWARD)
        self.assertEqual(first.state, PromotionState.PROMOTION_RECORD_CREATED.value)
        self.assertEqual(second.state, PromotionState.PROMOTION_RECORD_CREATED.value)
        self.assertIn(published_promotion_key(WALL, OLDER), store.objects)
        self.assertIn(published_promotion_key(WALL, FORWARD), store.objects)

    def test_16_older_promotion_cannot_become_projected_latest(self) -> None:
        older = promotion_record(
            wall_id=WALL, release_id=OLDER, name=NAME, promoted_at=WHEN, release_manifest_sha256="a" * 64
        )
        newer = promotion_record(
            wall_id=WALL, release_id=FORWARD, name=NAME, promoted_at=WHEN, release_manifest_sha256="b" * 64
        )
        catalog = project_catalog([older, newer])
        self.assertEqual(catalog["walls"][0]["latestReleaseId"], FORWARD)
        catalog_rev = project_catalog([newer, older])
        self.assertEqual(catalog_rev["walls"][0]["latestReleaseId"], FORWARD)

    def test_17_multiple_walls_preserved(self) -> None:
        records = [
            promotion_record(
                wall_id=OTHER_WALL,
                release_id=OTHER_RELEASE,
                name=OTHER_NAME,
                promoted_at=WHEN,
                release_manifest_sha256="c" * 64,
            ),
            promotion_record(
                wall_id=WALL, release_id=RELEASE, name=NAME, promoted_at=WHEN, release_manifest_sha256="d" * 64
            ),
        ]
        catalog = project_catalog(records)
        by_id = {item["wallId"]: item for item in catalog["walls"]}
        self.assertEqual(set(by_id), {WALL, OTHER_WALL})
        self.assertEqual(by_id[WALL]["latestReleaseId"], RELEASE)
        self.assertEqual(by_id[OTHER_WALL]["name"], OTHER_NAME)

    def test_18_conflicting_names_fail_closed(self) -> None:
        records = [
            promotion_record(
                wall_id=WALL, release_id=OLDER, name=NAME, promoted_at=WHEN, release_manifest_sha256="a" * 64
            ),
            promotion_record(
                wall_id=WALL, release_id=FORWARD, name="Other", promoted_at=WHEN, release_manifest_sha256="b" * 64
            ),
        ]
        with self.assertRaises(ProjectionError) as exc:
            project_catalog(records)
        self.assertEqual(exc.exception.code, "PROMOTION_NAME_CONFLICT")
        store = FakeObjectStore()
        seed_release(store, release_id=FORWARD)
        seed_promotion(store, wall_id=WALL, release_id=OLDER, name=NAME, manifest_sha="a" * 64)
        result = _promote(store, release_id=FORWARD, name="Other")
        self.assertEqual(result.reason_code, ReasonCode.PROMOTION_NAME_CONFLICT.value)
        self.assertNotIn(published_promotion_key(WALL, FORWARD), store.objects)

    def test_19_malformed_promotion_record_fail_closed(self) -> None:
        with self.assertRaises(ProjectionError) as exc:
            project_catalog([{"not": "a promotion"}])
        self.assertIn(exc.exception.code, {"PROMOTION_RECORD_INVALID", "PROMOTION_SCHEMA_UNSUPPORTED"})
        store = FakeObjectStore()
        seed_release(store)
        store.objects[published_promotion_key(WALL, RELEASE)] = b"{not-json"
        result = _promote(store)
        self.assertEqual(result.state, PromotionState.IMMUTABLE_PROMOTION_CONFLICT.value)
        self.assertEqual(store.absent_puts, [])

    def test_20_unsupported_promotion_schema_fail_closed(self) -> None:
        with self.assertRaises(ProjectionError) as exc:
            project_catalog([{"schema": "cragpal.wall-promotion.v2", "wallId": WALL}])
        self.assertEqual(exc.exception.code, "PROMOTION_SCHEMA_UNSUPPORTED")

    def test_21_duplicate_corrupt_promotion_identity_fail_closed(self) -> None:
        a = promotion_record(
            wall_id=WALL, release_id=RELEASE, name=NAME, promoted_at=WHEN, release_manifest_sha256="a" * 64
        )
        b = promotion_record(
            wall_id=WALL, release_id=RELEASE, name=NAME, promoted_at="2026-09-04T16:00:00Z", release_manifest_sha256="b" * 64
        )
        with self.assertRaises(ProjectionError) as exc:
            project_catalog([a, b])
        self.assertEqual(exc.exception.code, "PROMOTION_IDENTITY_CONFLICT")

    def test_22_deterministic_catalog_ordering(self) -> None:
        z_wall = promotion_record(
            wall_id="wall_zzz_01", release_id="r000001", name="Z", promoted_at=WHEN, release_manifest_sha256="a" * 64
        )
        a_wall = promotion_record(
            wall_id="wall_aaa_01", release_id="r000002", name="A", promoted_at=WHEN, release_manifest_sha256="b" * 64
        )
        first = project_catalog([z_wall, a_wall])
        second = project_catalog([a_wall, z_wall])
        self.assertEqual(first, second)
        self.assertEqual([item["wallId"] for item in first["walls"]], ["wall_aaa_01", "wall_zzz_01"])
        self.assertEqual(first["schema"], CATALOG_SCHEMA)

    def test_23_publisher_cannot_promote_automatically(self) -> None:
        from offline.publisher.pipeline import publish_localization_package
        from offline.tests.test_localization_package import RELEASE as PKG_REL
        from offline.tests.test_localization_package import WALL as PKG_WALL
        from offline.tests.test_localization_package import _candidate, _write
        from offline.localization_package.validate import validate_package_dir

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        package, manifest, assets, evidence = _candidate()
        root = _write(tmp, package, manifest, assets, evidence)
        self.assertTrue(validate_package_dir(root).ok)
        store = FakeObjectStore()
        result = publish_localization_package(
            wall_id=PKG_WALL,
            release_id=PKG_REL,
            package_dir=root,
            approve=True,
            store=store,
        )
        self.assertTrue(result.ok)
        self.assertFalse(any(key.startswith("published/promotions/") for key in store.puts))
        self.assertNotIn(CATALOG_KEY, store.puts)
        publisher = (ROOT / "offline" / "publisher" / "pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn("promote_localization_release", publisher)
        self.assertNotIn("put_if_absent", publisher)

    def test_24_build_still_cannot_publish_or_promote(self) -> None:
        from offline.wall_build.orchestrator import FORBIDDEN_COMMANDS

        self.assertIn("publish-localization-package", FORBIDDEN_COMMANDS)
        self.assertIn("promote-localization-release", FORBIDDEN_COMMANDS)

    def test_put_if_absent_is_promotion_only_and_never_overwrites(self) -> None:
        store = FakeObjectStore()
        with self.assertRaises(PublisherStoreError):
            store.put_if_absent(published_manifest_key(WALL, RELEASE), b"{}")
        with self.assertRaises(PublisherStoreError):
            store.put_if_absent(CATALOG_KEY, b"{}")
        key = published_promotion_key(WALL, RELEASE)
        store.put_if_absent(key, b"first")
        with self.assertRaises(ObjectAlreadyExists):
            store.put_if_absent(key, b"second")
        self.assertEqual(store.objects[key], b"first")

    def test_tencent_adapter_sends_forbid_overwrite(self) -> None:
        captured: dict[str, object] = {}

        class _Client:
            def put_object(self, **kwargs):
                captured.update(kwargs)

        adapter = TencentPromotionStore(client=_Client(), bucket="bucket")
        key = published_promotion_key(WALL, RELEASE)
        adapter.put_if_absent(key, b"{}")
        self.assertEqual(captured["ForbidOverwrite"], "true")
        self.assertNotIn("IfMatch", captured)
        self.assertNotIn("IfNoneMatch", captured)
        with self.assertRaises(PublisherStoreError):
            adapter.put_if_absent(CATALOG_KEY, b"{}")
        with self.assertRaises(PublisherStoreError):
            adapter.put_if_absent(published_manifest_key(WALL, RELEASE), b"{}")

    def test_tencent_adapter_maps_existing_object_conflict(self) -> None:
        class _Client:
            def put_object(self, **kwargs):
                exc = Exception("exists")
                exc.get_status_code = lambda: 409  # type: ignore[attr-defined]
                exc.get_error_code = lambda: "FileAlreadyExists"  # type: ignore[attr-defined]
                raise exc

        adapter = TencentPromotionStore(client=_Client(), bucket="bucket")
        with self.assertRaises(ObjectAlreadyExists):
            adapter.put_if_absent(published_promotion_key(WALL, RELEASE), b"{}")

    def test_publisher_adapter_cannot_write_promotions_or_catalog(self) -> None:
        class _Client:
            def get_object(self, **kwargs):
                raise AssertionError("must not reach client")

            def put_object(self, **kwargs):
                raise AssertionError("must not reach client")

        adapter = TencentPublisherStore(client=_Client(), bucket="unused")
        with self.assertRaises(Exception):
            adapter.put_bytes(CATALOG_KEY, b"{}")
        with self.assertRaises(Exception):
            adapter.put_bytes(published_promotion_key(WALL, RELEASE), b"{}")
        self.assertFalse(hasattr(adapter, "put_if_absent"))
        self.assertFalse(hasattr(adapter, "put_if_match"))

    def test_cli_without_approve_zero_writes(self) -> None:
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
        with patch("sys.stdout", io.StringIO()):
            first = run_promote_localization_release(WALL, RELEASE, name=NAME, approve=True, store=store)
        self.assertEqual(first, 0)
        self.assertEqual(store.absent_puts, [published_promotion_key(WALL, RELEASE)])
        with patch("sys.stdout", io.StringIO()):
            second = run_promote_localization_release(WALL, RELEASE, name=NAME, approve=True, store=store)
        self.assertEqual(second, 0)
        self.assertEqual(store.absent_puts, [published_promotion_key(WALL, RELEASE)])

    def test_rockvision_cli_requires_name_and_approve(self) -> None:
        spec = importlib.util.spec_from_file_location("rockvision_tools_cli_promo", ROOT / "tools" / "rockvision.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        tmp = Path(tempfile.mkdtemp())
        with patch("offline.catalog_promotion.cli.run_promote_localization_release", return_value=1) as fn:
            code = mod.main(["promote-localization-release", WALL, RELEASE, "--name", NAME], root=tmp)
        self.assertEqual(code, 1)
        self.assertFalse(fn.call_args.kwargs.get("approve"))
        with patch("offline.catalog_promotion.cli.run_promote_localization_release", return_value=0) as fn:
            code = mod.main(
                ["promote-localization-release", WALL, RELEASE, "--name", NAME, "--approve"],
                root=tmp,
            )
        self.assertEqual(code, 0)
        self.assertTrue(fn.call_args.kwargs.get("approve"))

    def test_production_path_has_no_etag_cas(self) -> None:
        sources = "\n".join(path.read_text(encoding="utf-8") for path in PROMOTION_DIR.glob("*.py"))
        promo_store = (ROOT / "offline" / "publisher" / "tencent_promotion_store.py").read_text(encoding="utf-8")
        protocol = (ROOT / "offline" / "publisher" / "store.py").read_text(encoding="utf-8")
        fake = (ROOT / "offline" / "publisher" / "fake_store.py").read_text(encoding="utf-8")
        for text in (sources, promo_store, protocol, fake):
            self.assertNotIn("put_if_match", text)
            self.assertNotIn("IfMatch", text)
            self.assertNotIn("IfNoneMatch", text)
            self.assertNotIn("If-None-Match", text)
        self.assertNotIn("delete_object", sources)
        self.assertNotIn("delete_object", promo_store)
        self.assertIn("ForbidOverwrite", promo_store)
        self.assertIn("x-cos-forbid-overwrite", promo_store)
        self.assertTrue(inspect.isclass(TencentPromotionStore))
        self.assertNotIn("wall_publisher_e2e_01", sources)

    def test_numeric_ordinal_not_lexicographic(self) -> None:
        low = promotion_record(
            wall_id=WALL, release_id="r000009", name=NAME, promoted_at=WHEN, release_manifest_sha256="a" * 64
        )
        high = promotion_record(
            wall_id=WALL, release_id="r000010", name=NAME, promoted_at=WHEN, release_manifest_sha256="b" * 64
        )
        catalog = project_catalog([low, high])
        self.assertEqual(catalog["walls"][0]["latestReleaseId"], "r000010")


if __name__ == "__main__":
    unittest.main()
