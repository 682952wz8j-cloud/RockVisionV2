"""Fake-COS publisher v1 tests. No real Tencent credentials or network."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.localization_package.layout import asset_path, cloud_manifest_path, evidence_path
from offline.localization_package.schema import ENVIRONMENT_DEVELOPMENT_TEST, STATE_PACKAGE_READY
from offline.localization_package.validate import validate_package_dir
from offline.publisher.cli import run_publish_localization_package
from offline.publisher.config import (
    DEFAULT_ENV_FILE,
    FORBIDDEN_RUNTIME_ENV,
    PublisherConfigError,
    load_publisher_config,
)
from offline.publisher.fake_store import FakeObjectStore
from offline.publisher.keys import (
    CATALOG_KEY,
    published_asset_key,
    published_catalog_key,
    published_manifest_key,
    published_promotion_key,
    published_release_prefix,
)
from offline.publisher.pipeline import publish_localization_package
from offline.publisher.schema import PublicationState, ReasonCode
from offline.publisher.store import PublisherStoreError
from offline.publisher.tencent_store import TencentPublisherStore
from offline.tests.test_localization_package import RELEASE, WALL, _candidate, _write

PUBLISHER_DIR = ROOT / "offline" / "publisher"
CANARY_SECRET = "cragpal-test-canary-AKIDEXAMPLE-not-a-real-key"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ready_package(tmp: Path) -> Path:
    package, manifest, assets, evidence = _candidate()
    root = _write(tmp, package, manifest, assets, evidence)
    result = validate_package_dir(root)
    assert result.ok and result.package_state == STATE_PACKAGE_READY
    assert result.route_ar_ready is False
    return root


def _asset_ids(root: Path) -> list[str]:
    payload = json.loads(cloud_manifest_path(root).read_text(encoding="utf-8"))
    return [item["assetId"] for item in payload["assets"]]


def _publisher_sources() -> list[Path]:
    return sorted(path for path in PUBLISHER_DIR.glob("*.py") if path.is_file())


class PublisherFakeCosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def _publish(self, root: Path, store: FakeObjectStore, **kwargs):
        params = {
            "wall_id": WALL,
            "release_id": RELEASE,
            "package_dir": root,
            "approve": True,
            "store": store,
        }
        params.update(kwargs)
        return publish_localization_package(**params)

    def test_01_missing_approval_zero_remote_calls(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        result = self._publish(root, store, approve=False)
        self.assertEqual(result.state, PublicationState.NOT_AUTHORIZED.value)
        self.assertEqual(result.reason_code, ReasonCode.PUBLISH_NOT_AUTHORIZED.value)
        self.assertFalse(result.published_release)
        self.assertEqual(store.calls, [])
        self.assertEqual(store.puts, [])
        self.assertEqual(store.gets, [])

    def test_02_package_not_ready_zero_writes(self) -> None:
        root = _ready_package(self.tmp)
        evidence_path(root, "freeze.json").unlink()
        store = FakeObjectStore()
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.LOCAL_PACKAGE_NOT_READY.value)
        self.assertTrue(result.validator_ran)
        self.assertEqual(store.calls, [])
        self.assertEqual(store.puts, [])

    def test_03_development_package_rejected(self) -> None:
        package, manifest, assets, evidence = _candidate(environment=ENVIRONMENT_DEVELOPMENT_TEST)
        root = _write(self.tmp, package, manifest, assets, evidence)
        self.assertTrue(validate_package_dir(root).ok)
        store = FakeObjectStore()
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.LOCAL_PACKAGE_NOT_READY.value)
        self.assertEqual(result.reason_code, ReasonCode.DEVELOPMENT_PACKAGE_NOT_PUBLISHABLE.value)
        self.assertEqual(store.calls, [])

    def test_04_invalid_wall_and_release_rejected(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        bad_wall = self._publish(root, store, wall_id="not a wall")
        self.assertEqual(bad_wall.state, PublicationState.LOCAL_PACKAGE_NOT_READY.value)
        self.assertEqual(bad_wall.reason_code, ReasonCode.INVALID_WALL_ID.value)
        store2 = FakeObjectStore()
        bad_rel = self._publish(root, store2, release_id="latest")
        self.assertEqual(bad_rel.state, PublicationState.LOCAL_PACKAGE_NOT_READY.value)
        self.assertEqual(bad_rel.reason_code, ReasonCode.INVALID_RELEASE_ID.value)
        self.assertEqual(store.calls, [])
        self.assertEqual(store2.calls, [])

    def test_05_06_07_clean_publish_assets_first_then_verified_manifest(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        store.objects[CATALOG_KEY] = b'{"schema":"cragpal.wall-catalog.v1","walls":[]}'
        catalog_before = store.objects[CATALOG_KEY]
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.PUBLISHED.value)
        self.assertTrue(result.published_release)
        self.assertFalse(result.catalog_discoverable)
        self.assertFalse(result.route_ar_ready)
        self.assertEqual(len(store.puts), 4)
        self.assertTrue(all("/assets/" in key for key in store.puts[:-1]))
        self.assertTrue(store.puts[-1].endswith("/manifest.json"))
        self.assertEqual(store.puts[-1], published_manifest_key(WALL, RELEASE))
        ids = _asset_ids(root)
        for asset_id in ids:
            key = published_asset_key(WALL, RELEASE, asset_id)
            local = asset_path(root, asset_id).read_bytes()
            remote = store.objects[key]
            self.assertEqual(remote, local)
            self.assertEqual(_sha(remote), _sha(local))
            self.assertEqual(len(remote), len(local))
            self.assertEqual(asset_id, Path(key).name)
        remote_manifest = store.objects[published_manifest_key(WALL, RELEASE)]
        self.assertEqual(remote_manifest, cloud_manifest_path(root).read_bytes())
        self.assertEqual(store.objects[CATALOG_KEY], catalog_before)
        self.assertNotIn(CATALOG_KEY, store.puts)
        self.assertNotIn(CATALOG_KEY, store.gets)
        self.assertEqual(store.overwrite_attempts, [])

    def test_08_asset_verification_failure_prevents_manifest(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        first = published_asset_key(WALL, RELEASE, _asset_ids(root)[0])
        store.corrupt_after_put.add(first)
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.REMOTE_VERIFY_FAILED.value)
        self.assertNotIn(published_manifest_key(WALL, RELEASE), store.puts)
        self.assertNotIn(published_manifest_key(WALL, RELEASE), store.objects)
        self.assertFalse(result.published_release)

    def test_09_preexisting_identical_asset_supports_retry(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        ids = _asset_ids(root)
        first_id = ids[0]
        first_key = published_asset_key(WALL, RELEASE, first_id)
        store.objects[first_key] = asset_path(root, first_id).read_bytes()
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.PUBLISHED.value)
        self.assertNotIn(first_key, store.puts)
        self.assertIn(first_key, result.already_identical)
        self.assertEqual(store.puts[-1], published_manifest_key(WALL, RELEASE))
        self.assertEqual(len(store.puts), 3)

    def test_10_preexisting_differing_asset_immutable_conflict(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        asset_id = _asset_ids(root)[0]
        key = published_asset_key(WALL, RELEASE, asset_id)
        original = b"different-remote-bytes"
        store.objects[key] = original
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.IMMUTABLE_RELEASE_CONFLICT.value)
        self.assertEqual(store.puts, [])
        self.assertEqual(store.objects[key], original)
        self.assertEqual(store.overwrite_attempts, [])
        self.assertNotIn(published_manifest_key(WALL, RELEASE), store.objects)

    def test_11_preexisting_identical_manifest_and_assets_idempotent(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        first = self._publish(root, store)
        self.assertEqual(first.state, PublicationState.PUBLISHED.value)
        store.puts.clear()
        store.calls.clear()
        store.overwrite_attempts.clear()
        second = self._publish(root, store)
        self.assertEqual(second.state, PublicationState.ALREADY_PUBLISHED_IDENTICAL.value)
        self.assertTrue(second.published_release)
        self.assertFalse(second.catalog_discoverable)
        self.assertEqual(store.puts, [])
        self.assertEqual(store.overwrite_attempts, [])

    def test_12_preexisting_differing_manifest_immutable_conflict(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        for asset_id in _asset_ids(root):
            store.objects[published_asset_key(WALL, RELEASE, asset_id)] = asset_path(root, asset_id).read_bytes()
        store.objects[published_manifest_key(WALL, RELEASE)] = b'{"schema":"nope"}'
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.IMMUTABLE_RELEASE_CONFLICT.value)
        self.assertEqual(store.puts, [])
        self.assertEqual(store.objects[published_manifest_key(WALL, RELEASE)], b'{"schema":"nope"}')

    def test_13_partial_prior_upload_resumes_safely(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        ids = _asset_ids(root)
        store.objects[published_asset_key(WALL, RELEASE, ids[0])] = asset_path(root, ids[0]).read_bytes()
        store.objects[published_asset_key(WALL, RELEASE, ids[1])] = asset_path(root, ids[1]).read_bytes()
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.PUBLISHED.value)
        self.assertEqual(
            store.puts,
            [
                published_asset_key(WALL, RELEASE, ids[2]),
                published_manifest_key(WALL, RELEASE),
            ],
        )

    def test_14_15_no_delete_and_no_overwrite_of_differing(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        self.assertFalse(hasattr(store, "delete_bytes"))
        self.assertFalse(hasattr(store, "delete_object"))
        asset_id = _asset_ids(root)[1]
        key = published_asset_key(WALL, RELEASE, asset_id)
        store.objects[key] = b"keep-me"
        self._publish(root, store)
        self.assertEqual(store.objects[key], b"keep-me")
        self.assertEqual(store.overwrite_attempts, [])

    def test_16_no_catalog_writes(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        store.objects[CATALOG_KEY] = b"untouched-catalog"
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.PUBLISHED.value)
        self.assertEqual(store.objects[CATALOG_KEY], b"untouched-catalog")
        self.assertNotIn(CATALOG_KEY, store.puts)
        self.assertNotIn(CATALOG_KEY, store.gets)
        pipeline = (PUBLISHER_DIR / "pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn("put_bytes(CATALOG_KEY", pipeline)
        self.assertNotIn('put_bytes("published/catalog.json"', pipeline)

    def test_17_no_list_bucket_dependency(self) -> None:
        store = FakeObjectStore()
        self.assertFalse(hasattr(store, "list_objects"))
        self.assertFalse(hasattr(store, "list_buckets"))
        for path in _publisher_sources():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("list_objects", text)
            self.assertNotIn("ListBucket", text)
            self.assertNotIn("list_buckets", text)

    def test_18_no_runtime_cam_env_dependency(self) -> None:
        with self.assertRaises(PublisherConfigError):
            load_publisher_config(
                {
                    "TENCENT_SECRET_ID": CANARY_SECRET,
                    "TENCENT_SECRET_KEY": CANARY_SECRET,
                    "TENCENT_COS_REGION": "ap-guangzhou",
                    "TENCENT_COS_BUCKET": "runtime-bucket",
                }
            )
        cfg = load_publisher_config(
            {
                "CRAGPAL_PUBLISHER_COS_REGION": "ap-guangzhou",
                "CRAGPAL_PUBLISHER_SECRET_ID": "publisher-id",
                "CRAGPAL_PUBLISHER_SECRET_KEY": CANARY_SECRET,
                "CRAGPAL_PUBLISHER_COS_BUCKET": "publisher-bucket",
            }
        )
        self.assertEqual(cfg.bucket, "publisher-bucket")
        self.assertNotIn(CANARY_SECRET, repr(cfg))
        for path in _publisher_sources():
            text = path.read_text(encoding="utf-8")
            if path.name == "config.py":
                for name in FORBIDDEN_RUNTIME_ENV:
                    self.assertIn(name, text)
                continue
            self.assertNotIn('os.environ["TENCENT_SECRET_ID"]', text)
            self.assertNotIn("os.environ['TENCENT_SECRET_ID']", text)

    def test_19_opaque_asset_id_preserved(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        self._publish(root, store)
        ids = _asset_ids(root)
        self.assertEqual(ids, ["stage3-descriptors", "stage3-landmarks", "s-wall-colmap"])
        for asset_id in ids:
            self.assertIn(published_asset_key(WALL, RELEASE, asset_id), store.objects)
        keys = " ".join(store.objects)
        self.assertNotIn("descriptors.bin", keys)
        self.assertNotIn("landmarks.json", keys)
        self.assertNotIn("S_wall_colmap.json", keys)

    def test_20_local_validator_rerun_immediately_before_publish(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        with patch("offline.publisher.pipeline.validate_package_dir", wraps=validate_package_dir) as fn:
            result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.PUBLISHED.value)
        self.assertGreaterEqual(fn.call_count, 1)
        self.assertTrue(result.validator_ran)
        fn.assert_called_with(root)

    def test_21_tampered_local_package_blocks_before_write(self) -> None:
        root = _ready_package(self.tmp)
        path = asset_path(root, _asset_ids(root)[0])
        path.write_bytes(path.read_bytes() + b"tamper")
        store = FakeObjectStore()
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.LOCAL_PACKAGE_NOT_READY.value)
        self.assertTrue(result.validator_ran)
        self.assertEqual(store.calls, [])

    def test_22_manifest_identity_mismatch_blocks(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        mismatch = self._publish(root, store, wall_id="wall_other_01")
        self.assertEqual(mismatch.state, PublicationState.LOCAL_PACKAGE_NOT_READY.value)
        self.assertIn(mismatch.reason_code, {ReasonCode.WALL_ID_MISMATCH.value, ReasonCode.INVALID_WALL_ID.value})
        self.assertEqual(store.calls, [])
        store2 = FakeObjectStore()
        store2.corrupt_after_put.add(published_manifest_key(WALL, RELEASE))
        result = self._publish(root, store2)
        self.assertEqual(result.state, PublicationState.REMOTE_VERIFY_FAILED.value)
        self.assertFalse(result.published_release)

    def test_23_route_ar_ready_false_still_publishable(self) -> None:
        root = _ready_package(self.tmp)
        self.assertFalse(validate_package_dir(root).route_ar_ready)
        store = FakeObjectStore()
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.PUBLISHED.value)
        self.assertFalse(result.route_ar_ready)

    def test_24_network_cos_exceptions_fail_closed(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        store.get_errors[published_asset_key(WALL, RELEASE, _asset_ids(root)[0])] = PublisherStoreError("timeout")
        result = self._publish(root, store)
        self.assertEqual(result.state, PublicationState.COS_ERROR.value)
        self.assertEqual(store.puts, [])
        store2 = FakeObjectStore()
        second = published_asset_key(WALL, RELEASE, _asset_ids(root)[1])
        store2.put_errors[second] = PublisherStoreError("put failed")
        result2 = self._publish(root, store2)
        self.assertEqual(result2.state, PublicationState.COS_ERROR.value)
        self.assertNotIn(published_manifest_key(WALL, RELEASE), store2.puts)
        self.assertNotIn(published_manifest_key(WALL, RELEASE), store2.objects)

    def test_25_secrets_never_logged(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        env = {
            "CRAGPAL_PUBLISHER_SECRET_ID": CANARY_SECRET,
            "CRAGPAL_PUBLISHER_SECRET_KEY": CANARY_SECRET,
        }
        buf = io.StringIO()
        logger = logging.getLogger("offline.publisher")
        handler = logging.StreamHandler(buf)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            with patch("sys.stdout", buf):
                code = run_publish_localization_package(
                    WALL,
                    RELEASE,
                    approve=True,
                    root=self.tmp,
                    package_dir=root,
                    store=store,
                    environ=env,
                )
        finally:
            logger.removeHandler(handler)
        self.assertEqual(code, 0)
        text = buf.getvalue()
        self.assertNotIn(CANARY_SECRET, text)
        self.assertNotIn("SecretId", text)
        self.assertNotIn("SecretKey", text)
        self.assertIn("PACKAGE_READY: YES", text)
        self.assertIn("LOCALIZATION_READY: YES", text)
        self.assertIn("ROUTE_AR_READY: NO", text)

    def test_cli_without_approve_makes_zero_store_calls(self) -> None:
        root = _ready_package(self.tmp)
        store = FakeObjectStore()
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = run_publish_localization_package(
                WALL,
                RELEASE,
                approve=False,
                root=self.tmp,
                package_dir=root,
                store=store,
            )
        self.assertEqual(code, 1)
        self.assertEqual(store.calls, [])
        self.assertIn("publish not authorized", buf.getvalue())

    def test_cli_does_not_construct_real_store_when_package_not_ready(self) -> None:
        root = _ready_package(self.tmp)
        evidence_path(root, "freeze.json").unlink()
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            with patch("offline.publisher.cli.TencentPublisherStore.from_config") as factory:
                code = run_publish_localization_package(
                    WALL,
                    RELEASE,
                    approve=True,
                    root=self.tmp,
                    package_dir=root,
                )
        self.assertEqual(code, 1)
        factory.assert_not_called()

    def test_keys_match_backend_contract(self) -> None:
        from backend.app.contract import (
            published_asset_key as backend_asset,
            published_catalog_key as backend_catalog,
            published_manifest_key as backend_manifest,
        )

        self.assertEqual(published_catalog_key(), backend_catalog())
        self.assertEqual(published_manifest_key(WALL, RELEASE), backend_manifest(WALL, RELEASE))
        self.assertEqual(
            published_asset_key(WALL, RELEASE, "stage3-descriptors"),
            backend_asset(WALL, RELEASE, "stage3-descriptors"),
        )
        self.assertEqual(published_release_prefix(WALL, RELEASE), f"published/{WALL}/{RELEASE}/")

    def test_tencent_adapter_refuses_catalog_and_has_no_delete(self) -> None:
        class _Client:
            def get_object(self, **kwargs):
                raise AssertionError("catalog must not reach client")

            def put_object(self, **kwargs):
                raise AssertionError("catalog must not reach client")

        adapter = TencentPublisherStore(client=_Client(), bucket="unused")
        with self.assertRaises(Exception):
            adapter.get_bytes(CATALOG_KEY)
        with self.assertRaises(Exception):
            adapter.put_bytes(CATALOG_KEY, b"{}")
        with self.assertRaises(Exception):
            adapter.put_bytes(published_promotion_key(WALL, RELEASE), b"{}")
        self.assertFalse(hasattr(adapter, "delete_object"))
        self.assertFalse(hasattr(adapter, "list_objects"))
        self.assertFalse(hasattr(adapter, "put_if_match"))

    def test_default_env_file_is_outside_repo(self) -> None:
        self.assertFalse(str(DEFAULT_ENV_FILE).startswith(str(ROOT)))
        self.assertEqual(DEFAULT_ENV_FILE, Path.home() / ".config" / "cragpal" / "publisher.env")

    def test_publisher_source_has_no_delete_object(self) -> None:
        for path in _publisher_sources():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("delete_object", text)
            self.assertNotIn("delete_objects", text)

    def test_rockvision_cli_requires_exact_ids_and_approve(self) -> None:
        spec = importlib.util.spec_from_file_location("rockvision_tools_cli_pub", ROOT / "tools" / "rockvision.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        with patch("offline.publisher.cli.run_publish_localization_package", return_value=1) as fn:
            code = mod.main(["publish-localization-package", WALL, RELEASE], root=self.tmp)
        self.assertEqual(code, 1)
        self.assertFalse(fn.call_args.kwargs.get("approve"))
        with patch("offline.publisher.cli.run_publish_localization_package", return_value=0) as fn:
            code = mod.main(
                ["publish-localization-package", WALL, RELEASE, "--approve", "--package-dir", str(self.tmp / "pkg")],
                root=self.tmp,
            )
        self.assertEqual(code, 0)
        self.assertTrue(fn.call_args.kwargs.get("approve"))
        self.assertEqual(fn.call_args.args[0], WALL)
        self.assertEqual(fn.call_args.args[1], RELEASE)


if __name__ == "__main__":
    unittest.main()
