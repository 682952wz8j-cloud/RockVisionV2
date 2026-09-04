"""Local Production Localization Package E2E (synthetic). Not a real wall.

Package construct/validate remain Python APIs. Production Stage 3 is the
existing `build_reference_matching(..., run_id=)` path (same as
`./rockvision reference-match <wall> --run-id <runId>`).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image

from offline.colmap.source_identity import (
    PROVENANCE_ORIGIN_RECONSTRUCTION_RUN,
    SELECTED_MODEL_RELATIVE_PATH,
    model_fingerprint,
)
from offline.ingestion.hashing import sha256_file
from offline.localization_package.cloud_manifest import local_cloud_manifest
from offline.localization_package.construct import write_package_candidate
from offline.localization_package.layout import asset_path, cloud_manifest_path, evidence_path, package_json_path
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
from offline.reference_matching.pipeline import build_reference_matching, output_dir
from offline.reference_matching.production_run import (
    REASON_FINGERPRINT_MISMATCH,
    ProductionStage3BindError,
    resolve_production_stage3_inputs,
    wall_build_run_dir,
)
from offline.wall_build.states import Stage, StageStatus

WALL = "wall_pkg_e2e_01"
RELEASE = "r000008"
RUN_ID = "wb_20260904T120000Z_e2e0001"
JPEG_NAME = "DJI_0001.JPG"
JPEG_REL = JPEG_NAME
CREATED_AT = "2026-09-04T12:00:00Z"
WIDTH = 256
HEIGHT = 192


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_runtime() -> str | None:
    try:
        import pycolmap  # noqa: F401
    except ImportError:
        return "pycolmap required for synthetic sparse COLMAP E2E"
    from offline.reference_matching.opencv_env import provenance_payload

    status = provenance_payload(ROOT).get("status")
    if status != "PINNED_SOURCE_MATCH":
        return "pinned OpenCV 4.14 CLI required for production Stage 3 E2E"
    return None


def _link_pins(tmp: Path) -> None:
    (tmp / "offline").mkdir(parents=True, exist_ok=True)
    ios = tmp / "ios"
    vendor = tmp / "offline" / "vendor"
    if not ios.exists():
        ios.symlink_to(ROOT / "ios")
    if not vendor.exists():
        vendor.symlink_to(ROOT / "offline" / "vendor")


def _write_checkerboard_jpeg(path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            value = 255 if ((x // 16) + (y // 16)) % 2 == 0 else 0
            pixels[x, y] = (value, value, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="JPEG", quality=95, optimize=False, subsampling=0)


def _write_sparse_model(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    pairs: list[str] = []
    points: list[str] = []
    index = 0
    for y in range(24, HEIGHT - 8, 24):
        for x in range(24, WIDTH - 8, 24):
            pid = index + 1
            pairs.extend([f"{x}.0", f"{y}.0", str(pid)])
            points.append(f"{pid} {x / 10:.1f} {y / 10:.1f} 1.0 255 0 0 0 1 {index}")
            index += 1
    (model_dir / "cameras.txt").write_text(
        "# CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n"
        f"1 SIMPLE_RADIAL {WIDTH} {HEIGHT} 200 {WIDTH / 2} {HEIGHT / 2} 0\n",
        encoding="utf-8",
    )
    (model_dir / "images.txt").write_text(
        "# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n"
        f"1 1 0 0 0 0 0 0 1 {JPEG_NAME}\n"
        + " ".join(pairs)
        + "\n\n",
        encoding="utf-8",
    )
    (model_dir / "points3D.txt").write_text(
        "# POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)\n" + "\n".join(points) + "\n",
        encoding="utf-8",
    )


def _pass_stages() -> dict:
    stages = {}
    for name in (
        "INPUT_FREEZE",
        Stage.STAGE2_SELECTION.value,
        Stage.HEIGHT_VERTICAL_DATUM.value,
        Stage.POSITIONING_QUALITY.value,
        Stage.RECONSTRUCTION.value,
        Stage.METRIC_REGISTRATION.value,
    ):
        stages[name] = {"status": StageStatus.AUTO_PASS.value}
    stages[Stage.RECONSTRUCTION.value]["gateResult"] = "PASS"
    stages[Stage.METRIC_REGISTRATION.value]["gateResult"] = "PASS"
    stages[Stage.METRIC_REGISTRATION.value]["validationStatus"] = "VALIDATED"
    stages[Stage.METRIC_REGISTRATION.value]["sWallColmapWritten"] = True
    return stages


@dataclass
class SyntheticProductionWorkspace:
    root: Path
    wall_id: str
    run_id: str
    fingerprint: str
    jpeg_sha: str
    jpeg_rel: str
    run_dir: Path
    model_dir: Path
    sim3_path: Path
    identity_path: Path
    freeze_dir: Path


def build_synthetic_validated_run(root: Path) -> SyntheticProductionWorkspace:
    """Authoritative wall_build/<runId> that the production Stage 3 resolver accepts."""
    _link_pins(root)
    jpeg = root / "incoming" / WALL / JPEG_NAME
    _write_checkerboard_jpeg(jpeg)
    jpeg_sha = sha256_file(jpeg)
    run_dir = wall_build_run_dir(root, WALL, RUN_ID)
    model_dir = run_dir / "colmap" / "sparse" / "best"
    _write_sparse_model(model_dir)
    fingerprint = model_fingerprint(model_dir)
    identity = {
        "schemaVersion": "colmap_source_identity.1",
        "provenanceOrigin": PROVENANCE_ORIGIN_RECONSTRUCTION_RUN,
        "wallId": WALL,
        "selectedModelRelativePath": SELECTED_MODEL_RELATIVE_PATH,
        "modelFingerprint": fingerprint,
        "colmapSourceIdentityReasonCode": "COLMAP_SOURCE_IDENTITY_PROVEN",
        "colmapSourceIdentityExecutionAllowed": True,
        "selectedImageRelativePaths": [JPEG_REL],
        "selectedImageSha256": {JPEG_REL: jpeg_sha},
    }
    _write_json(run_dir / "colmap" / "colmap_source_identity.json", identity)
    sim3 = {
        "schemaVersion": "S_wall_colmap.1",
        "name": "S_wall_colmap",
        "status": "VALIDATED",
        "sourceFrame": "colmap_reconstruction_rhs_opencv_units",
        "targetFrame": "wall_local_metres",
        "convention": "X_wall = s * R * X_colmap + t  (column vectors)",
        "scale": 1.25,
        "rotationMatrix": {"layout": "row-major 3x3", "values": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]},
        "translationMeters": [0.0, 0.0, 0.0],
        "matrix4x4": {"layout": "row-major", "values": [[1.25, 0, 0, 0], [0, 1.25, 0, 0], [0, 0, 1.25, 0], [0, 0, 0, 1]]},
        "wallId": WALL,
        "wallBuildRunId": RUN_ID,
        "colmapModelFingerprint": fingerprint,
        "modelFingerprint": fingerprint,
    }
    sim3_path = run_dir / "metric_registration" / "S_wall_colmap.json"
    _write_json(sim3_path, sim3)
    _write_json(
        run_dir / "wall_build_report.json",
        {
            "schemaVersion": "wallBuild.report.1",
            "wallId": WALL,
            "runId": RUN_ID,
            "stageStatuses": _pass_stages(),
            "automationReached": "METRIC_REGISTRATION_COMPLETE",
            "runTerminalStatus": "DEVELOPMENT_GATE_REVIEW_REQUIRED",
        },
    )
    _write_json(
        run_dir / "stage2_input_selection.json",
        {
            "schemaVersion": "stage2_input_selection.4",
            "selectionStatus": "AUTO_PASS",
            "wallId": WALL,
            "runId": RUN_ID,
            "selectedImageSha256": {JPEG_REL: jpeg_sha},
        },
    )
    _write_json(
        run_dir / "positioning_quality.json",
        {
            "positioningQualityExecutionAllowed": True,
            "positioningQualityReasonCode": "POSITIONING_QUALITY_FIXED",
            "positioningQualityProvenance": "AUTO_PASS",
        },
    )
    _write_json(run_dir / "height_vertical_datum.json", {"heightGateExecutionAllowed": True})
    return SyntheticProductionWorkspace(
        root=root,
        wall_id=WALL,
        run_id=RUN_ID,
        fingerprint=fingerprint,
        jpeg_sha=jpeg_sha,
        jpeg_rel=JPEG_REL,
        run_dir=run_dir,
        model_dir=model_dir,
        sim3_path=sim3_path,
        identity_path=run_dir / "colmap" / "colmap_source_identity.json",
        freeze_dir=output_dir(root, WALL, run_dir=run_dir),
    )


def run_production_stage3(ws: SyntheticProductionWorkspace) -> dict:
    bind = resolve_production_stage3_inputs(ws.root, ws.wall_id, ws.run_id)
    if bind.model_fingerprint != ws.fingerprint:
        raise AssertionError("live modelFingerprint drifted before Stage 3")
    payload = build_reference_matching(ws.wall_id, ws.root, run_id=ws.run_id)
    payload["_bind"] = bind
    return payload


def construct_localization_package(ws: SyntheticProductionWorkspace) -> Path:
    freeze = _read_json(ws.freeze_dir / "freeze.json")
    descriptors = (ws.freeze_dir / "descriptors.bin").read_bytes()
    landmarks = (ws.freeze_dir / "landmarks.json").read_bytes()
    sim3 = ws.sim3_path.read_bytes()
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
    package = {
        "schema": PACKAGE_SCHEMA,
        "wallId": ws.wall_id,
        "releaseId": RELEASE,
        "environment": ENVIRONMENT_PRODUCTION,
        "capabilities": {"localizationReady": False, "routeArReady": False},
        "sourceBuild": {
            "runId": ws.run_id,
            "selection": {"schema": "stage2_input_selection.4", "selectionStatus": "AUTO_PASS"},
            "selectedSourceJpegSha256": {ws.jpeg_rel: ws.jpeg_sha},
            "positioningQuality": {
                "positioningQualityExecutionAllowed": True,
                "positioningQualityReasonCode": "POSITIONING_QUALITY_FIXED",
            },
            "heightDatum": {"heightGateExecutionAllowed": True},
            "colmapSourceIdentity": {
                "modelFingerprint": ws.fingerprint,
                "colmapSourceIdentityReasonCode": "COLMAP_SOURCE_IDENTITY_PROVEN",
                "colmapSourceIdentityExecutionAllowed": True,
            },
        },
        "metricTransform": metric_spec,
        "stage3": {
            "descriptors": desc_spec,
            "landmarks": land_spec,
            "freezeIdentity": {
                "colmapModelFingerprint": freeze["colmapModelFingerprint"],
                "wallBuildRunId": freeze["wallBuildRunId"],
            },
        },
        "routes": {"present": False, "authorized": False},
        "packageState": STATE_CONSTRUCTED,
    }
    evidence = {
        "stage2_input_selection.json": _read_json(ws.run_dir / "stage2_input_selection.json"),
        "positioning_quality.json": _read_json(ws.run_dir / "positioning_quality.json"),
        "height_vertical_datum.json": _read_json(ws.run_dir / "height_vertical_datum.json"),
        "colmap_source_identity.json": _read_json(ws.identity_path),
        "freeze.json": freeze,
    }
    manifest = local_cloud_manifest(
        wall_id=ws.wall_id,
        release_id=RELEASE,
        created_at=CREATED_AT,
        descriptors=desc_spec,
        landmarks=land_spec,
        metric=metric_spec,
    )
    dest = ws.root / "offline" / "packages" / ws.wall_id / RELEASE
    write_package_candidate(
        dest,
        package=package,
        cloud_manifest=manifest,
        assets={
            desc_spec["assetId"]: descriptors,
            land_spec["assetId"]: landmarks,
            metric_spec["assetId"]: sim3,
        },
        evidence=evidence,
    )
    return dest


def _copy_package(src: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


def _rewrite(path: Path, mutator) -> None:
    payload = _read_json(path)
    mutator(payload)
    _write_json(path, payload)


def _retarget_asset(root: Path, asset_id: str, data: bytes, *, package_key: tuple[str, ...]) -> None:
    asset_path(root, asset_id).write_bytes(data)
    digest = _sha(data)
    size = len(data)

    def _pkg(payload):
        cursor = payload
        for key in package_key[:-1]:
            cursor = cursor[key]
        cursor[package_key[-1]]["sha256"] = digest
        cursor[package_key[-1]]["bytes"] = size

    _rewrite(package_json_path(root), _pkg)

    def _man(payload):
        for item in payload["assets"]:
            if item["assetId"] == asset_id:
                item["sha256"] = digest
                item["bytes"] = size

    _rewrite(cloud_manifest_path(root), _man)


class LocalizationPackageE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reason = _require_runtime()
        if reason:
            raise unittest.SkipTest(reason)

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_pkg_e2e_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _positive(self) -> tuple[SyntheticProductionWorkspace, Path, dict]:
        ws = build_synthetic_validated_run(self.tmp)
        payload = run_production_stage3(ws)
        package_root = construct_localization_package(ws)
        return ws, package_root, payload

    def test_positive_local_package_e2e(self) -> None:
        ws, package_root, payload = self._positive()
        freeze = _read_json(ws.freeze_dir / "freeze.json")
        landmarks = _read_json(ws.freeze_dir / "landmarks.json")
        sim3 = _read_json(ws.sim3_path)
        identity = _read_json(ws.identity_path)
        live_fp = model_fingerprint(ws.model_dir)

        self.assertTrue(payload.get("productionBound"))
        self.assertFalse(payload.get("legacyFallback"))
        self.assertEqual(payload.get("runId"), RUN_ID)
        self.assertEqual(payload.get("gate"), "3C")
        self.assertEqual(payload.get("stage"), "compatibility_human_review")
        self.assertEqual(payload.get("gateResult"), "NEEDS REVIEW")
        self.assertTrue(payload.get("humanReviewRequired"))
        self.assertTrue(payload.get("stopBeforeSwift"))
        self.assertNotEqual(payload.get("gateResult"), "PASS")
        self.assertGreater(freeze["descriptorCount"], 0)
        self.assertFalse(landmarks["developmentFixtureOnly"])
        self.assertFalse(landmarks["notAWallPackage"])
        self.assertEqual(landmarks["wallId"], WALL)
        self.assertEqual(freeze["wallId"], WALL)
        self.assertEqual(freeze["wallBuildRunId"], RUN_ID)
        self.assertEqual(freeze["colmapModelFingerprint"], ws.fingerprint)
        self.assertEqual(freeze["colmapModelFingerprint"], live_fp)
        self.assertEqual(identity["modelFingerprint"], live_fp)
        self.assertEqual(sim3["wallId"], WALL)
        self.assertEqual(sim3["wallBuildRunId"], RUN_ID)
        self.assertEqual(sim3["colmapModelFingerprint"], live_fp)

        constructed = _read_json(package_json_path(package_root))
        self.assertEqual(constructed["packageState"], STATE_CONSTRUCTED)
        self.assertFalse(constructed["capabilities"]["localizationReady"])
        self.assertFalse((package_root / "routes.json").exists())
        self.assertFalse((package_root / "routes").exists())

        result = validate_package_dir(package_root)
        self.assertEqual(result.package_state, STATE_PACKAGE_READY)
        self.assertTrue(result.localization_ready)
        self.assertFalse(result.route_ar_ready)
        self.assertEqual(result.reason_codes, [])
        self.assertTrue(result.ok)

        self.assertEqual(constructed["wallId"], identity["wallId"])
        self.assertEqual(identity["wallId"], sim3["wallId"])
        self.assertEqual(sim3["wallId"], landmarks["wallId"])
        self.assertEqual(landmarks["wallId"], freeze["wallId"])
        self.assertEqual(constructed["sourceBuild"]["runId"], sim3["wallBuildRunId"])
        self.assertEqual(sim3["wallBuildRunId"], freeze["wallBuildRunId"])
        self.assertEqual(identity["modelFingerprint"], sim3["colmapModelFingerprint"])
        self.assertEqual(sim3["colmapModelFingerprint"], freeze["colmapModelFingerprint"])
        self.assertEqual(freeze["descriptorsSha256"], constructed["stage3"]["descriptors"]["sha256"])
        self.assertEqual(freeze["landmarksSha256"], constructed["stage3"]["landmarks"]["sha256"])
        self.assertEqual(freeze["descriptorsSha256"], _sha((ws.freeze_dir / "descriptors.bin").read_bytes()))
        self.assertEqual(freeze["landmarksSha256"], _sha((ws.freeze_dir / "landmarks.json").read_bytes()))

    def test_construction_is_not_validation(self) -> None:
        ws, package_root, _payload = self._positive()
        constructed = _read_json(package_json_path(package_root))
        self.assertEqual(constructed["packageState"], STATE_CONSTRUCTED)
        self.assertNotEqual(constructed["packageState"], STATE_PACKAGE_READY)
        self.assertFalse(constructed["capabilities"]["localizationReady"])
        result = validate_package_dir(package_root)
        self.assertEqual(result.package_state, STATE_PACKAGE_READY)
        self.assertTrue(result.localization_ready)

    def test_tamper_matrix_fail_closed(self) -> None:
        ws, package_root, _payload = self._positive()
        self.assertTrue(validate_package_dir(package_root).ok)
        cases = [
            ("A_wallId", lambda root: _rewrite(package_json_path(root), lambda p: p.update({"wallId": "wall_pkg_e2e_other"})), ReasonCode.WALL_ID_MISMATCH),
            ("B_runId", lambda root: _rewrite(package_json_path(root), lambda p: p["sourceBuild"].update({"runId": "wb_other_run"})), ReasonCode.FREEZE_WALL_BUILD_RUN_MISMATCH),
            ("C_sim3_wall", lambda root: self._tamper_sim3(root, {"wallId": "wall_pkg_e2e_other"}), ReasonCode.WALL_ID_MISMATCH),
            ("D_sim3_run", lambda root: self._tamper_sim3(root, {"wallBuildRunId": "wb_other_run"}), ReasonCode.SIM3_WALL_BUILD_RUN_MISMATCH),
            ("E_sim3_fp", lambda root: self._tamper_sim3(root, {"colmapModelFingerprint": hashlib.sha256(b"other-model").hexdigest(), "modelFingerprint": hashlib.sha256(b"other-model").hexdigest()}), ReasonCode.SIM3_MODEL_FINGERPRINT_MISMATCH),
            ("F_freeze_wall", lambda root: _rewrite(evidence_path(root, "freeze.json"), lambda p: p.update({"wallId": "wall_pkg_e2e_other"})), ReasonCode.WALL_ID_MISMATCH),
            ("G_freeze_run", lambda root: _rewrite(evidence_path(root, "freeze.json"), lambda p: p.update({"wallBuildRunId": "wb_other_run"})), ReasonCode.FREEZE_WALL_BUILD_RUN_MISMATCH),
            ("H_freeze_fp", lambda root: _rewrite(evidence_path(root, "freeze.json"), lambda p: p.update({"colmapModelFingerprint": hashlib.sha256(b"other-fp").hexdigest()})), ReasonCode.FREEZE_MODEL_FINGERPRINT_MISMATCH),
            ("I_desc_bytes", lambda root: asset_path(root, "stage3-descriptors").write_bytes(asset_path(root, "stage3-descriptors").read_bytes() + b"x"), ReasonCode.ASSET_HASH_MISMATCH),
            ("J_land_bytes", lambda root: asset_path(root, "stage3-landmarks").write_bytes(asset_path(root, "stage3-landmarks").read_bytes() + b"x"), ReasonCode.ASSET_HASH_MISMATCH),
            ("K_sim3_bytes", lambda root: asset_path(root, "s-wall-colmap").write_bytes(asset_path(root, "s-wall-colmap").read_bytes() + b"\n"), ReasonCode.ASSET_HASH_MISMATCH),
            ("L_dev_fixture", lambda root: self._tamper_landmark_flag(root, "developmentFixtureOnly", True), ReasonCode.DEVELOPMENT_FIXTURE_NOT_PRODUCTION),
            ("M_not_wall_pkg", lambda root: self._tamper_landmark_flag(root, "notAWallPackage", True), ReasonCode.NOT_A_WALL_PACKAGE_FLAG),
            ("N_pq", lambda root: _rewrite(evidence_path(root, "positioning_quality.json"), lambda p: p.update({"positioningQualityExecutionAllowed": False, "positioningQualityReasonCode": "POSITIONING_QUALITY_NOT_PROVEN"})), ReasonCode.POSITIONING_QUALITY_NOT_PASS),
            ("O_height", lambda root: _rewrite(evidence_path(root, "height_vertical_datum.json"), lambda p: p.update({"heightGateExecutionAllowed": False})), ReasonCode.HEIGHT_GATE_NOT_PASS),
            ("P_identity", lambda root: _rewrite(evidence_path(root, "colmap_source_identity.json"), lambda p: p.update({"colmapSourceIdentityExecutionAllowed": False, "colmapSourceIdentityReasonCode": "COLMAP_SOURCE_IDENTITY_NOT_PROVEN"})), ReasonCode.COLMAP_SOURCE_IDENTITY_NOT_PROVEN),
            ("R_routes", lambda root: (root / "routes.json").write_text("{}\n", encoding="utf-8"), ReasonCode.ROUTES_NOT_AUTHORIZED),
            ("S_route_ar", lambda root: _rewrite(package_json_path(root), lambda p: p["capabilities"].update({"routeArReady": True})), ReasonCode.ROUTES_NOT_AUTHORIZED),
        ]
        for name, mutator, expected in cases:
            clone = _copy_package(package_root, self.tmp / "tampers" / name)
            mutator(clone)
            result = validate_package_dir(clone)
            self.assertNotEqual(result.package_state, STATE_PACKAGE_READY, name)
            self.assertFalse(result.ok, name)
            self.assertFalse(result.localization_ready, name)
            self.assertIn(expected.value, result.reason_codes, f"{name} expected {expected.value} got {result.reason_codes}")
        self.assertTrue(validate_package_dir(package_root).ok)

    def test_q_live_colmap_fingerprint_mismatch_blocks_stage3(self) -> None:
        ws = build_synthetic_validated_run(self.tmp)
        (ws.model_dir / "points3D.txt").write_bytes((ws.model_dir / "points3D.txt").read_bytes() + b"#tamper\n")
        self.assertNotEqual(model_fingerprint(ws.model_dir), ws.fingerprint)
        with self.assertRaises(ProductionStage3BindError) as ctx:
            resolve_production_stage3_inputs(ws.root, WALL, RUN_ID)
        self.assertEqual(ctx.exception.code, REASON_FINGERPRINT_MISMATCH)

    def test_reproducibility_two_fresh_workspaces(self) -> None:
        first_root = Path(tempfile.mkdtemp(prefix="rv_pkg_e2e_a_"))
        second_root = Path(tempfile.mkdtemp(prefix="rv_pkg_e2e_b_"))
        try:
            first = self._run_isolated(first_root)
            second = self._run_isolated(second_root)
            self.assertEqual(first["descriptorsSha256"], second["descriptorsSha256"])
            self.assertEqual(first["landmarksSha256"], second["landmarksSha256"])
            self.assertEqual(first["fingerprint"], second["fingerprint"])
            self.assertEqual(first["freeze"]["wallId"], second["freeze"]["wallId"])
            self.assertEqual(first["freeze"]["wallBuildRunId"], second["freeze"]["wallBuildRunId"])
            self.assertEqual(first["freeze"]["colmapModelFingerprint"], second["freeze"]["colmapModelFingerprint"])
            self.assertEqual(first["sim3Sha256"], second["sim3Sha256"])
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
        finally:
            shutil.rmtree(first_root, ignore_errors=True)
            shutil.rmtree(second_root, ignore_errors=True)

    def test_real_walls_are_not_this_fixture(self) -> None:
        self.assertNotEqual(WALL, "wall_jiulongfeng_01")
        self.assertNotEqual(WALL, "wall_jinshidong_01")
        self.assertFalse(WALL.endswith("_dev"))
        fixture = ROOT / "ios" / "RockVision" / "Resources" / "DevelopmentFixture" / "landmarks.json"
        if fixture.is_file():
            payload = json.loads(fixture.read_text(encoding="utf-8"))
            self.assertTrue(payload.get("developmentFixtureOnly"))
            self.assertTrue(payload.get("notAWallPackage"))
        self.assertNotIn("jinshidong", WALL)
        self.assertNotIn("jiulongfeng", WALL)

    def test_network_free_and_no_routes(self) -> None:
        modules = [
            ROOT / "offline" / "localization_package" / "construct.py",
            ROOT / "offline" / "localization_package" / "validate.py",
            ROOT / "offline" / "reference_matching" / "production_run.py",
            ROOT / "offline" / "reference_matching" / "pipeline.py",
        ]
        for path in modules:
            text = path.read_text(encoding="utf-8")
            for token in ("tencentcloud", "SecretId", "SecretKey", "put_object", "boto3", "requests.get"):
                self.assertNotIn(token, text, path.name)
        ws, package_root, _payload = self._positive()
        self.assertFalse((package_root / "routes.json").exists())
        self.assertFalse((ws.run_dir / "routes.json").exists())
        result = validate_package_dir(package_root)
        self.assertFalse(result.route_ar_ready)

    def test_gate3c_needs_review_is_outside_package_readiness(self) -> None:
        ws, package_root, payload = self._positive()
        self.assertEqual(payload["gateResult"], "NEEDS REVIEW")
        self.assertTrue((ws.freeze_dir / "freeze.json").is_file())
        review = ws.freeze_dir / "gate3c_compatibility_review.json"
        self.assertTrue(review.is_file())
        self.assertEqual(_read_json(review)["gateResult"], "NEEDS REVIEW")
        self.assertFalse((package_root / "evidence" / "gate3c_compatibility_review.json").is_file())
        result = validate_package_dir(package_root)
        self.assertTrue(result.ok)
        planted = package_root / "evidence" / "gate3c_compatibility_review.json"
        planted.write_text(json.dumps({"gateResult": "FAIL", "stage": "compatibility_human_review"}, indent=2) + "\n", encoding="utf-8")
        still = validate_package_dir(package_root)
        self.assertTrue(still.ok)
        self.assertEqual(still.package_state, STATE_PACKAGE_READY)

    def _tamper_sim3(self, root: Path, updates: dict) -> None:
        path = asset_path(root, "s-wall-colmap")
        payload = _read_json(path)
        payload.update(updates)
        raw = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        _retarget_asset(root, "s-wall-colmap", raw, package_key=("metricTransform",))

    def _tamper_landmark_flag(self, root: Path, key: str, value: bool) -> None:
        path = asset_path(root, "stage3-landmarks")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload[key] = value
        raw = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        _retarget_asset(root, "stage3-landmarks", raw, package_key=("stage3", "landmarks"))
        _rewrite(evidence_path(root, "freeze.json"), lambda freeze: freeze.update({"landmarksSha256": _sha(raw), "landmarksBytes": len(raw)}))

    def _run_isolated(self, root: Path) -> dict:
        ws = build_synthetic_validated_run(root)
        run_production_stage3(ws)
        package_root = construct_localization_package(ws)
        freeze = _read_json(ws.freeze_dir / "freeze.json")
        result = validate_package_dir(package_root)
        return {
            "descriptorsSha256": freeze["descriptorsSha256"],
            "landmarksSha256": freeze["landmarksSha256"],
            "fingerprint": ws.fingerprint,
            "freeze": freeze,
            "sim3Sha256": _sha(ws.sim3_path.read_bytes()),
            "ok": result.ok,
        }


if __name__ == "__main__":
    unittest.main()
