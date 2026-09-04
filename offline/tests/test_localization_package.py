from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.localization_package.cloud_manifest import local_cloud_manifest
from offline.localization_package.construct import write_package_candidate
from offline.localization_package.layout import asset_path, evidence_path, package_json_path, packages_root, required_evidence_names
from offline.localization_package.package_schema import PackageSchemaError, decode_package_json, is_release_id
from offline.localization_package.schema import (
    ENVIRONMENT_PRODUCTION,
    PACKAGE_SCHEMA,
    ReasonCode,
    STATE_CONSTRUCTED,
    STATE_PACKAGE_READY,
    TYPE_DESCRIPTORS,
    TYPE_LANDMARKS,
    TYPE_S_WALL_COLMAP,
)
from offline.localization_package.validate import validate_package_dir

WALL = "wall_pkg_contract_01"
RELEASE = "r000007"
RUN_ID = "wb_20260904_pkgphasea"
FINGERPRINT = hashlib.sha256(b"synthetic-colmap-model").hexdigest()
JPEG_REL = "DJI_0001.JPG"
JPEG_SHA = hashlib.sha256(b"synthetic-jpeg").hexdigest()
CREATED_AT = "2026-09-04T00:00:00Z"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sim3(*, status: str = "VALIDATED", wall_id: str = WALL, fingerprint: str = FINGERPRINT, scale: float = 1.25) -> dict:
    return {
        "schemaVersion": "S_wall_colmap.1",
        "name": "S_wall_colmap",
        "status": status,
        "sourceFrame": "colmap_reconstruction_rhs_opencv_units",
        "targetFrame": "wall_local_metres",
        "convention": "X_wall = s * R * X_colmap + t  (column vectors)",
        "scale": scale,
        "rotationMatrix": {"layout": "row-major 3x3", "values": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]},
        "translationMeters": [0.0, 0.0, 0.0],
        "matrix4x4": {
            "layout": "row-major",
            "values": [[scale, 0.0, 0.0, 0.0], [0.0, scale, 0.0, 0.0], [0.0, 0.0, scale, 0.0], [0.0, 0.0, 0.0, 1.0]],
        },
        "wallId": wall_id,
        "wallBuildRunId": RUN_ID,
        "colmapModelFingerprint": fingerprint,
        "modelFingerprint": fingerprint,
    }


def _landmarks(*, wall_id: str = WALL, development_fixture: bool = False, not_a_wall_package: bool = False) -> dict:
    return {
        "schema": 1,
        "schemaId": "reference_matching.baseline_2px.1",
        "wallId": wall_id,
        "developmentFixtureOnly": development_fixture,
        "notAWallPackage": not_a_wall_package,
        "landmarks": [],
    }


def _candidate(*, bind_stage3: bool = True, environment: str = ENVIRONMENT_PRODUCTION):
    descriptors = b"RVS1-synthetic-descriptors"
    landmarks = json.dumps(_landmarks(), ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    sim3 = json.dumps(_sim3(), indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    desc_spec = {
        "assetId": "stage3-descriptors",
        "type": TYPE_DESCRIPTORS,
        "schema": "RVS1",
        "sha256": _sha(descriptors),
        "bytes": len(descriptors),
    }
    land_spec = {
        "assetId": "stage3-landmarks",
        "type": TYPE_LANDMARKS,
        "schema": 1,
        "sha256": _sha(landmarks),
        "bytes": len(landmarks),
    }
    metric_spec = {
        "assetId": "s-wall-colmap",
        "type": TYPE_S_WALL_COLMAP,
        "status": "VALIDATED",
        "source": "S_wall_colmap.json",
        "sha256": _sha(sim3),
        "bytes": len(sim3),
    }
    freeze = {
        "wallId": WALL,
        "descriptorsPath": "descriptors.bin",
        "landmarksPath": "landmarks.json",
        "descriptorsSha256": desc_spec["sha256"],
        "landmarksSha256": land_spec["sha256"],
        "descriptorsBytes": desc_spec["bytes"],
        "landmarksBytes": land_spec["bytes"],
    }
    freeze_identity: dict | None
    if bind_stage3:
        freeze["colmapModelFingerprint"] = FINGERPRINT
        freeze["wallBuildRunId"] = RUN_ID
        freeze_identity = {"colmapModelFingerprint": FINGERPRINT, "wallBuildRunId": RUN_ID}
    else:
        freeze_identity = {}
    package = {
        "schema": PACKAGE_SCHEMA,
        "wallId": WALL,
        "releaseId": RELEASE,
        "environment": environment,
        "capabilities": {"localizationReady": False, "routeArReady": False},
        "sourceBuild": {
            "runId": RUN_ID,
            "selection": {"schema": "stage2_input_selection.4", "selectionStatus": "AUTO_PASS"},
            "selectedSourceJpegSha256": {JPEG_REL: JPEG_SHA},
            "positioningQuality": {
                "positioningQualityExecutionAllowed": True,
                "positioningQualityReasonCode": "POSITIONING_QUALITY_FIXED",
            },
            "heightDatum": {"heightGateExecutionAllowed": True},
            "colmapSourceIdentity": {
                "modelFingerprint": FINGERPRINT,
                "colmapSourceIdentityReasonCode": "COLMAP_SOURCE_IDENTITY_PROVEN",
                "colmapSourceIdentityExecutionAllowed": True,
            },
        },
        "metricTransform": metric_spec,
        "stage3": {
            "descriptors": desc_spec,
            "landmarks": land_spec,
            "freezeIdentity": freeze_identity,
        },
        "routes": {"present": False, "authorized": False},
        "packageState": STATE_CONSTRUCTED,
    }
    evidence = {
        "stage2_input_selection.json": {
            "schemaVersion": "stage2_input_selection.4",
            "selectionStatus": "AUTO_PASS",
            "wallId": WALL,
            "selectedImageSha256": {JPEG_REL: JPEG_SHA},
        },
        "positioning_quality.json": {
            "positioningQualityExecutionAllowed": True,
            "positioningQualityReasonCode": "POSITIONING_QUALITY_FIXED",
            "positioningQualityProvenance": "AUTO_PASS",
        },
        "height_vertical_datum.json": {"heightGateExecutionAllowed": True},
        "colmap_source_identity.json": {
            "wallId": WALL,
            "modelFingerprint": FINGERPRINT,
            "colmapSourceIdentityReasonCode": "COLMAP_SOURCE_IDENTITY_PROVEN",
            "colmapSourceIdentityExecutionAllowed": True,
        },
        "freeze.json": freeze,
    }
    manifest = local_cloud_manifest(
        wall_id=WALL,
        release_id=RELEASE,
        created_at=CREATED_AT,
        descriptors=desc_spec,
        landmarks=land_spec,
        metric=metric_spec,
    )
    assets = {
        desc_spec["assetId"]: descriptors,
        land_spec["assetId"]: landmarks,
        metric_spec["assetId"]: sim3,
    }
    return package, manifest, assets, evidence


def _write(tmp: Path, package, manifest, assets, evidence) -> Path:
    root = tmp / "offline" / "packages" / package["wallId"] / package["releaseId"]
    write_package_candidate(root, package=package, cloud_manifest=manifest, assets=assets, evidence=evidence)
    return root


def _rewrite_package(root: Path, mutator) -> None:
    path = package_json_path(root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutator(payload)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _rewrite_json(path: Path, mutator) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutator(payload)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class LocalizationPackageSchemaTests(unittest.TestCase):
    def test_01_valid_package_schema_decoding(self) -> None:
        package, *_ = _candidate()
        decoded = decode_package_json(package)
        self.assertEqual(decoded["schema"], PACKAGE_SCHEMA)
        self.assertEqual(decoded["environment"], ENVIRONMENT_PRODUCTION)
        self.assertIn("localizationReady", decoded["capabilities"])
        self.assertIn("routeArReady", decoded["capabilities"])
        self.assertFalse(decoded["capabilities"]["localizationReady"])
        self.assertFalse(decoded["capabilities"]["routeArReady"])
        self.assertEqual(decoded["stage3"]["descriptors"]["type"], TYPE_DESCRIPTORS)
        self.assertEqual(decoded["stage3"]["landmarks"]["type"], TYPE_LANDMARKS)
        self.assertEqual(decoded["metricTransform"]["type"], TYPE_S_WALL_COLMAP)

    def test_02_unsafe_wall_id_rejected(self) -> None:
        package, *_ = _candidate()
        package["wallId"] = "../etc"
        with self.assertRaises(PackageSchemaError) as ctx:
            decode_package_json(package)
        self.assertEqual(ctx.exception.code, ReasonCode.INVALID_WALL_ID)

    def test_03_invalid_release_id_rejected(self) -> None:
        self.assertFalse(is_release_id("r1"))
        self.assertFalse(is_release_id("R000007"))
        self.assertFalse(is_release_id("release-1"))
        package, *_ = _candidate()
        package["releaseId"] = "r7"
        with self.assertRaises(PackageSchemaError) as ctx:
            decode_package_json(package)
        self.assertEqual(ctx.exception.code, ReasonCode.INVALID_RELEASE_ID)

    def test_05_localization_and_route_capabilities_are_distinct(self) -> None:
        package, *_ = _candidate()
        self.assertIn("localizationReady", package["capabilities"])
        self.assertIn("routeArReady", package["capabilities"])
        self.assertIsNot(package["capabilities"]["localizationReady"], object())
        package["capabilities"]["localizationReady"] = True
        package["capabilities"]["routeArReady"] = False
        decoded = decode_package_json(package)
        self.assertTrue(decoded["capabilities"]["localizationReady"])
        self.assertFalse(decoded["capabilities"]["routeArReady"])
        package["routes"]["authorized"] = True
        with self.assertRaises(PackageSchemaError) as ctx:
            decode_package_json(package)
        self.assertEqual(ctx.exception.code, ReasonCode.ROUTES_NOT_AUTHORIZED)


class LocalizationPackageValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_locpkg_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ready(self, **kwargs):
        package, manifest, assets, evidence = _candidate(**kwargs)
        root = _write(self.tmp, package, manifest, assets, evidence)
        return root, package

    def test_04_production_environment_recognized(self) -> None:
        root, _ = self._ready()
        result = validate_package_dir(root)
        self.assertEqual(result.environment, ENVIRONMENT_PRODUCTION)
        self.assertEqual(result.package_state, STATE_PACKAGE_READY)
        self.assertTrue(result.localization_ready)
        self.assertFalse(result.route_ar_ready)

    def test_06_07_08_required_asset_identities(self) -> None:
        package, *_ = _candidate()
        self.assertEqual(package["stage3"]["descriptors"]["type"], TYPE_DESCRIPTORS)
        self.assertEqual(package["stage3"]["landmarks"]["type"], TYPE_LANDMARKS)
        self.assertEqual(package["metricTransform"]["type"], TYPE_S_WALL_COLMAP)
        root, _ = self._ready()
        result = validate_package_dir(root)
        self.assertEqual(result.reason_codes, [])
        self.assertTrue((root / "assets" / "stage3-descriptors").is_file())
        self.assertTrue((root / "assets" / "stage3-landmarks").is_file())
        self.assertTrue((root / "assets" / "s-wall-colmap").is_file())

    def test_09_descriptor_hash_mismatch_fails(self) -> None:
        root, _ = self._ready()
        asset_path(root, "stage3-descriptors").write_bytes(b"tampered-descriptors")
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.ASSET_HASH_MISMATCH.value, result.reason_codes)
        self.assertNotEqual(result.package_state, STATE_PACKAGE_READY)

    def test_10_landmark_hash_mismatch_fails(self) -> None:
        root, _ = self._ready()
        asset_path(root, "stage3-landmarks").write_bytes(b'{"tampered":true}\n')
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.ASSET_HASH_MISMATCH.value, result.reason_codes)
        self.assertFalse(result.localization_ready)

    def test_11_sim3_hash_mismatch_fails(self) -> None:
        root, _ = self._ready()
        asset_path(root, "s-wall-colmap").write_bytes(b'{"status":"VALIDATED"}\n')
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.ASSET_HASH_MISMATCH.value, result.reason_codes)
        self.assertFalse(result.ok)

    def test_12_sim3_not_validated_fails(self) -> None:
        package, manifest, assets, evidence = _candidate()
        computed = _sim3(status="computed")
        raw = json.dumps(computed, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        assets["s-wall-colmap"] = raw
        package["metricTransform"]["sha256"] = _sha(raw)
        package["metricTransform"]["bytes"] = len(raw)
        package["metricTransform"]["status"] = "computed"
        manifest["assets"][2]["sha256"] = package["metricTransform"]["sha256"]
        manifest["assets"][2]["bytes"] = package["metricTransform"]["bytes"]
        root = _write(self.tmp, package, manifest, assets, evidence)
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.SIM3_NOT_VALIDATED.value, result.reason_codes)
        self.assertFalse(result.localization_ready)

    def test_13_positioning_quality_not_pass_fails(self) -> None:
        root, _ = self._ready()
        _rewrite_json(
            evidence_path(root, "positioning_quality.json"),
            lambda payload: payload.update(
                {
                    "positioningQualityExecutionAllowed": False,
                    "positioningQualityReasonCode": "POSITIONING_QUALITY_NOT_PROVEN",
                }
            ),
        )
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.POSITIONING_QUALITY_NOT_PASS.value, result.reason_codes)

    def test_14_height_gate_not_pass_fails(self) -> None:
        root, _ = self._ready()
        _rewrite_json(
            evidence_path(root, "height_vertical_datum.json"),
            lambda payload: payload.update({"heightGateExecutionAllowed": False}),
        )
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.HEIGHT_GATE_NOT_PASS.value, result.reason_codes)

    def test_15_colmap_source_identity_not_proven_fails(self) -> None:
        root, _ = self._ready()
        _rewrite_json(
            evidence_path(root, "colmap_source_identity.json"),
            lambda payload: payload.update(
                {
                    "colmapSourceIdentityExecutionAllowed": False,
                    "colmapSourceIdentityReasonCode": "COLMAP_SOURCE_IDENTITY_NOT_PROVEN",
                }
            ),
        )
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.COLMAP_SOURCE_IDENTITY_NOT_PROVEN.value, result.reason_codes)

    def test_16_development_fixture_fails_production(self) -> None:
        package, manifest, assets, evidence = _candidate()
        land = _landmarks(development_fixture=True, not_a_wall_package=False)
        raw = json.dumps(land, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        assets["stage3-landmarks"] = raw
        package["stage3"]["landmarks"]["sha256"] = _sha(raw)
        package["stage3"]["landmarks"]["bytes"] = len(raw)
        package["stage3"]["freezeIdentity"]["colmapModelFingerprint"] = FINGERPRINT
        evidence["freeze.json"]["landmarksSha256"] = _sha(raw)
        evidence["freeze.json"]["landmarksBytes"] = len(raw)
        manifest["assets"][1]["sha256"] = _sha(raw)
        manifest["assets"][1]["bytes"] = len(raw)
        root = _write(self.tmp, package, manifest, assets, evidence)
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.DEVELOPMENT_FIXTURE_NOT_PRODUCTION.value, result.reason_codes)
        self.assertNotEqual(result.package_state, STATE_PACKAGE_READY)

    def test_17_not_a_wall_package_fails_production(self) -> None:
        package, manifest, assets, evidence = _candidate()
        land = _landmarks(development_fixture=False, not_a_wall_package=True)
        raw = json.dumps(land, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        assets["stage3-landmarks"] = raw
        package["stage3"]["landmarks"]["sha256"] = _sha(raw)
        package["stage3"]["landmarks"]["bytes"] = len(raw)
        evidence["freeze.json"]["landmarksSha256"] = _sha(raw)
        evidence["freeze.json"]["landmarksBytes"] = len(raw)
        manifest["assets"][1]["sha256"] = _sha(raw)
        manifest["assets"][1]["bytes"] = len(raw)
        root = _write(self.tmp, package, manifest, assets, evidence)
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.NOT_A_WALL_PACKAGE_FLAG.value, result.reason_codes)

    def test_18_stage3_reference_map_binding_absent_fails_closed(self) -> None:
        root, _ = self._ready(bind_stage3=False)
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.STAGE3_REFERENCE_MAP_BINDING_NOT_PROVEN.value, result.reason_codes)
        self.assertFalse(result.localization_ready)
        self.assertNotEqual(result.package_state, STATE_PACKAGE_READY)

    def test_19_wall_id_mismatch_fails(self) -> None:
        root, _ = self._ready()
        land = _landmarks(wall_id="wall_other_01")
        raw = json.dumps(land, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        asset_path(root, "stage3-landmarks").write_bytes(raw)
        _rewrite_package(
            root,
            lambda payload: payload["stage3"]["landmarks"].update({"sha256": _sha(raw), "bytes": len(raw)}),
        )
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.WALL_ID_MISMATCH.value, result.reason_codes)

    def test_20_no_routes_required_for_localization_ready(self) -> None:
        root, _ = self._ready()
        self.assertFalse((root / "routes.json").exists())
        self.assertFalse((root / "routes").exists())
        result = validate_package_dir(root)
        self.assertTrue(result.localization_ready)
        self.assertFalse(result.route_ar_ready)

    def test_21_routes_are_not_authorized_by_this_package(self) -> None:
        root, _ = self._ready()
        (root / "routes.json").write_text("{}\n", encoding="utf-8")
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.ROUTES_NOT_AUTHORIZED.value, result.reason_codes)
        self.assertFalse(result.route_ar_ready)
        self.assertFalse(result.localization_ready)

    def test_22_no_cos_or_network_required(self) -> None:
        import offline.localization_package as pkg
        import offline.localization_package.cloud_manifest as cloud
        import offline.localization_package.construct as construct
        import offline.localization_package.validate as validate

        for module in (pkg, cloud, construct, validate):
            text = Path(module.__file__).read_text(encoding="utf-8")
            for token in ("tencentcloud", "SecretId", "SecretKey", "put_object", "boto3", "requests.get"):
                self.assertNotIn(token, text)
        root, _ = self._ready()
        result = validate_package_dir(root)
        self.assertTrue(result.ok)

    def test_gate3c_compatibility_review_is_not_package_evidence(self) -> None:
        self.assertNotIn("gate3c_compatibility_review.json", required_evidence_names())
        root, _ = self._ready()
        planted = evidence_path(root, "gate3c_compatibility_review.json")
        planted.write_text(json.dumps({"gateResult": "FAIL", "humanReviewRequired": True}, indent=2) + "\n", encoding="utf-8")
        result = validate_package_dir(root)
        self.assertTrue(result.ok)
        self.assertEqual(result.package_state, STATE_PACKAGE_READY)

    def test_jinshidong_style_positioning_quality_not_package_ready(self) -> None:
        root, _ = self._ready()
        _rewrite_json(
            evidence_path(root, "positioning_quality.json"),
            lambda payload: payload.update(
                {
                    "positioningQualityExecutionAllowed": False,
                    "positioningQualityReasonCode": "POSITIONING_QUALITY_NOT_PROVEN",
                }
            ),
        )
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.POSITIONING_QUALITY_NOT_PASS.value, result.reason_codes)
        self.assertNotEqual(result.package_state, STATE_PACKAGE_READY)

    def test_jiulongfeng_development_fixture_not_production_package_ready(self) -> None:
        package, manifest, assets, evidence = _candidate(bind_stage3=False)
        land = _landmarks(development_fixture=True, not_a_wall_package=True)
        raw = json.dumps(land, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        assets["stage3-landmarks"] = raw
        package["stage3"]["landmarks"]["sha256"] = _sha(raw)
        package["stage3"]["landmarks"]["bytes"] = len(raw)
        evidence["freeze.json"]["landmarksSha256"] = _sha(raw)
        manifest["assets"][1]["sha256"] = _sha(raw)
        manifest["assets"][1]["bytes"] = len(raw)
        root = _write(self.tmp, package, manifest, assets, evidence)
        result = validate_package_dir(root)
        self.assertEqual(result.environment, ENVIRONMENT_PRODUCTION)
        self.assertIn(ReasonCode.DEVELOPMENT_FIXTURE_NOT_PRODUCTION.value, result.reason_codes)
        self.assertIn(ReasonCode.NOT_A_WALL_PACKAGE_FLAG.value, result.reason_codes)
        self.assertIn(ReasonCode.STAGE3_REFERENCE_MAP_BINDING_NOT_PROVEN.value, result.reason_codes)
        self.assertNotEqual(result.package_state, STATE_PACKAGE_READY)

    def test_construction_cannot_claim_package_ready(self) -> None:
        package, manifest, assets, evidence = _candidate()
        package["packageState"] = STATE_PACKAGE_READY
        with self.assertRaises(ValueError):
            write_package_candidate(self.tmp / "x", package=package, cloud_manifest=manifest, assets=assets, evidence=evidence)

    def test_layout_is_offline_packages_not_published(self) -> None:
        root, _ = self._ready()
        self.assertIn("offline/packages", root.as_posix())
        self.assertNotIn("/published/", root.as_posix())
        self.assertEqual(packages_root(ROOT), ROOT / "offline" / "packages")
        self.assertFalse((root / "published").exists())

    def test_copied_files_are_not_automatically_package_ready_without_binding(self) -> None:
        root, _ = self._ready(bind_stage3=False)
        result = validate_package_dir(root)
        self.assertEqual(json.loads(package_json_path(root).read_text())["packageState"], STATE_CONSTRUCTED)
        self.assertEqual(result.package_state, "NOT_PACKAGE_READY")

    def test_sim3_without_explicit_wall_identity_fails_closed(self) -> None:
        package, manifest, assets, evidence = _candidate()
        sim3 = _sim3()
        del sim3["wallId"]
        raw = json.dumps(sim3, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        assets["s-wall-colmap"] = raw
        package["metricTransform"]["sha256"] = _sha(raw)
        package["metricTransform"]["bytes"] = len(raw)
        manifest["assets"][2]["sha256"] = _sha(raw)
        manifest["assets"][2]["bytes"] = len(raw)
        root = _write(self.tmp, package, manifest, assets, evidence)
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.WALL_ID_MISMATCH.value, result.reason_codes)
        self.assertFalse(result.ok)

    def test_sim3_run_mismatch_fails(self) -> None:
        package, manifest, assets, evidence = _candidate()
        sim3 = _sim3()
        sim3["wallBuildRunId"] = "wb_other_run"
        raw = json.dumps(sim3, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        assets["s-wall-colmap"] = raw
        package["metricTransform"]["sha256"] = _sha(raw)
        package["metricTransform"]["bytes"] = len(raw)
        manifest["assets"][2]["sha256"] = _sha(raw)
        manifest["assets"][2]["bytes"] = len(raw)
        root = _write(self.tmp, package, manifest, assets, evidence)
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.SIM3_WALL_BUILD_RUN_MISMATCH.value, result.reason_codes)
        self.assertFalse(result.ok)

    def test_sim3_model_fingerprint_mismatch_fails(self) -> None:
        package, manifest, assets, evidence = _candidate()
        sim3 = _sim3()
        other = hashlib.sha256(b"other-model").hexdigest()
        sim3["colmapModelFingerprint"] = other
        sim3["modelFingerprint"] = other
        raw = json.dumps(sim3, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        assets["s-wall-colmap"] = raw
        package["metricTransform"]["sha256"] = _sha(raw)
        package["metricTransform"]["bytes"] = len(raw)
        manifest["assets"][2]["sha256"] = _sha(raw)
        manifest["assets"][2]["bytes"] = len(raw)
        root = _write(self.tmp, package, manifest, assets, evidence)
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.SIM3_MODEL_FINGERPRINT_MISMATCH.value, result.reason_codes)

    def test_freeze_run_mismatch_fails(self) -> None:
        root, _ = self._ready()
        _rewrite_json(evidence_path(root, "freeze.json"), lambda payload: payload.update({"wallBuildRunId": "wb_other"}))
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.FREEZE_WALL_BUILD_RUN_MISMATCH.value, result.reason_codes)

    def test_freeze_model_fingerprint_mismatch_fails(self) -> None:
        root, _ = self._ready()
        _rewrite_json(
            evidence_path(root, "freeze.json"),
            lambda payload: payload.update({"colmapModelFingerprint": hashlib.sha256(b"other").hexdigest()}),
        )
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.FREEZE_MODEL_FINGERPRINT_MISMATCH.value, result.reason_codes)

    def test_historical_sim3_missing_provenance_cannot_qualify(self) -> None:
        package, manifest, assets, evidence = _candidate()
        sim3 = _sim3()
        for key in ("wallId", "wallBuildRunId", "colmapModelFingerprint", "modelFingerprint"):
            sim3.pop(key, None)
        raw = json.dumps(sim3, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        assets["s-wall-colmap"] = raw
        package["metricTransform"]["sha256"] = _sha(raw)
        package["metricTransform"]["bytes"] = len(raw)
        manifest["assets"][2]["sha256"] = _sha(raw)
        manifest["assets"][2]["bytes"] = len(raw)
        root = _write(self.tmp, package, manifest, assets, evidence)
        result = validate_package_dir(root)
        self.assertTrue(
            {
                ReasonCode.WALL_ID_MISMATCH.value,
                ReasonCode.SIM3_WALL_BUILD_RUN_MISMATCH.value,
                ReasonCode.COLMAP_SOURCE_IDENTITY_NOT_PROVEN.value,
            }.issubset(set(result.reason_codes))
        )
        self.assertNotEqual(result.package_state, STATE_PACKAGE_READY)

    def test_historical_freeze_missing_provenance_cannot_qualify(self) -> None:
        root, _ = self._ready(bind_stage3=False)
        result = validate_package_dir(root)
        self.assertIn(ReasonCode.STAGE3_REFERENCE_MAP_BINDING_NOT_PROVEN.value, result.reason_codes)
        self.assertNotEqual(result.package_state, STATE_PACKAGE_READY)


if __name__ == "__main__":
    unittest.main()
