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

from offline.colmap.source_identity import (
    PROVENANCE_ORIGIN_RECONSTRUCTION_RUN,
    SELECTED_MODEL_RELATIVE_PATH,
    model_fingerprint,
)
from offline.ingestion.hashing import sha256_file
from offline.reference_matching.pipeline import build_reference_matching, output_dir
from offline.reference_matching.production_run import (
    REASON_FINGERPRINT_MISMATCH,
    REASON_GATES_NOT_PASS,
    REASON_RUN_ID_MISMATCH,
    REASON_RUN_NOT_FOUND,
    REASON_SIM3_PROVENANCE_NOT_PROVEN,
    ProductionStage3BindError,
    legacy_stage3_paths,
    resolve_production_stage3_inputs,
    wall_build_run_dir,
)
from offline.wall_build.states import Stage, StageStatus

WALL = "wall_stage3_bind_01"
RUN_A = "wb_20260904T000001Z_aaaa1111"
RUN_B = "wb_20260904T000002Z_bbbb2222"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sim3(*, wall_id: str, run_id: str, fingerprint: str, status: str = "VALIDATED") -> dict:
    return {
        "schemaVersion": "S_wall_colmap.1",
        "name": "S_wall_colmap",
        "status": status,
        "sourceFrame": "colmap_reconstruction_rhs_opencv_units",
        "targetFrame": "wall_local_metres",
        "convention": "X_wall = s * R * X_colmap + t  (column vectors)",
        "scale": 1.25,
        "rotationMatrix": {"layout": "row-major 3x3", "values": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]},
        "translationMeters": [0.0, 0.0, 0.0],
        "matrix4x4": {"layout": "row-major", "values": [[1.25, 0, 0, 0], [0, 1.25, 0, 0], [0, 0, 1.25, 0], [0, 0, 0, 1]]},
        "wallId": wall_id,
        "wallBuildRunId": run_id,
        "colmapModelFingerprint": fingerprint,
        "modelFingerprint": fingerprint,
    }


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


def _write_run(root: Path, wall_id: str, run_id: str, *, token: bytes = b"model-a", stages: dict | None = None, sim3_extra: dict | None = None, report_wall: str | None = None, report_run: str | None = None) -> str:
    run_dir = wall_build_run_dir(root, wall_id, run_id)
    model_dir = run_dir / "colmap" / "sparse" / "best"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "cameras.bin").write_bytes(token + b"-cam")
    (model_dir / "images.bin").write_bytes(token + b"-img")
    (model_dir / "points3D.bin").write_bytes(token + b"-pts")
    fingerprint = model_fingerprint(model_dir)
    _write_json(
        run_dir / "colmap" / "colmap_source_identity.json",
        {
            "schemaVersion": "colmap_source_identity.1",
            "provenanceOrigin": PROVENANCE_ORIGIN_RECONSTRUCTION_RUN,
            "wallId": wall_id,
            "selectedModelRelativePath": SELECTED_MODEL_RELATIVE_PATH,
            "modelFingerprint": fingerprint,
        },
    )
    sim3 = _sim3(wall_id=wall_id, run_id=run_id, fingerprint=fingerprint)
    if sim3_extra:
        sim3.update(sim3_extra)
    _write_json(run_dir / "metric_registration" / "S_wall_colmap.json", sim3)
    report = {
        "schemaVersion": "wallBuild.report.1",
        "wallId": report_wall if report_wall is not None else wall_id,
        "runId": report_run if report_run is not None else run_id,
        "stageStatuses": stages if stages is not None else _pass_stages(),
        "automationReached": "METRIC_REGISTRATION_COMPLETE",
        "runTerminalStatus": "DEVELOPMENT_GATE_REVIEW_REQUIRED",
    }
    _write_json(run_dir / "wall_build_report.json", report)
    return fingerprint


class ProductionStage3RunBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_s3bind_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_01_explicit_validated_run_accepted(self) -> None:
        fingerprint = _write_run(self.tmp, WALL, RUN_A)
        bind = resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)
        self.assertEqual(bind.run_id, RUN_A)
        self.assertEqual(bind.model_fingerprint, fingerprint)
        self.assertEqual(bind.sim3["colmapModelFingerprint"], fingerprint)
        self.assertEqual(
            bind.model_dir.resolve(),
            (wall_build_run_dir(self.tmp, WALL, RUN_A) / "colmap" / "sparse" / "best").resolve(),
        )

    def test_02_missing_run_rejected(self) -> None:
        with self.assertRaises(ProductionStage3BindError) as ctx:
            resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)
        self.assertEqual(ctx.exception.code, REASON_RUN_NOT_FOUND)

    def test_03_wrong_run_id_rejected(self) -> None:
        _write_run(self.tmp, WALL, RUN_A, report_run="wb_other")
        with self.assertRaises(ProductionStage3BindError) as ctx:
            resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)
        self.assertEqual(ctx.exception.code, REASON_RUN_ID_MISMATCH)

    def test_04_no_automatic_latest_run_selection(self) -> None:
        fp_a = _write_run(self.tmp, WALL, RUN_A, token=b"old")
        fp_b = _write_run(self.tmp, WALL, RUN_B, token=b"new")
        bind = resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)
        self.assertEqual(bind.run_id, RUN_A)
        self.assertEqual(bind.model_fingerprint, fp_a)
        self.assertNotEqual(fp_a, fp_b)

    def test_05_production_mode_has_no_legacy_fallback(self) -> None:
        legacy_sparse, legacy_sim3 = legacy_stage3_paths(self.tmp, WALL)
        legacy_sparse.mkdir(parents=True, exist_ok=True)
        (legacy_sparse / "images.bin").write_bytes(b"legacy")
        _write_json(legacy_sim3, _sim3(wall_id=WALL, run_id="legacy", fingerprint="nope"))
        payload = build_reference_matching(WALL, self.tmp, run_id=RUN_A)
        self.assertEqual(payload["gateResult"], "STOP")
        self.assertEqual(payload["reasonCode"], REASON_RUN_NOT_FOUND)
        self.assertFalse(payload["legacyFallback"])
        self.assertFalse(output_dir(self.tmp, WALL).exists())

    def test_06_stage2_gate_failure_blocks_production_stage3(self) -> None:
        stages = _pass_stages()
        stages[Stage.POSITIONING_QUALITY.value] = {
            "status": StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": "POSITIONING_QUALITY_NOT_PROVEN",
        }
        _write_run(self.tmp, WALL, RUN_A, stages=stages)
        with self.assertRaises(ProductionStage3BindError) as ctx:
            resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)
        self.assertEqual(ctx.exception.code, REASON_GATES_NOT_PASS)

    def test_07_model_fingerprint_from_authoritative_identity(self) -> None:
        fingerprint = _write_run(self.tmp, WALL, RUN_A)
        bind = resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)
        self.assertEqual(bind.identity["modelFingerprint"], fingerprint)
        self.assertEqual(bind.model_fingerprint, fingerprint)

    def test_08_caller_cannot_spoof_model_fingerprint(self) -> None:
        fingerprint = _write_run(self.tmp, WALL, RUN_A)
        identity_path = wall_build_run_dir(self.tmp, WALL, RUN_A) / "colmap" / "colmap_source_identity.json"
        payload = json.loads(identity_path.read_text(encoding="utf-8"))
        payload["modelFingerprint"] = hashlib.sha256(b"spoof").hexdigest()
        identity_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(ProductionStage3BindError) as ctx:
            resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)
        self.assertEqual(ctx.exception.code, REASON_FINGERPRINT_MISMATCH)
        self.assertNotEqual(payload["modelFingerprint"], fingerprint)

    def test_09_10_11_sim3_records_wall_run_and_fingerprint(self) -> None:
        fingerprint = _write_run(self.tmp, WALL, RUN_A)
        bind = resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)
        self.assertEqual(bind.sim3["wallId"], WALL)
        self.assertEqual(bind.sim3["wallBuildRunId"], RUN_A)
        self.assertEqual(bind.sim3["colmapModelFingerprint"], fingerprint)

    def test_28_jinshidong_style_pq_failure_blocks_before_stage3(self) -> None:
        stages = _pass_stages()
        stages[Stage.POSITIONING_QUALITY.value] = {
            "status": StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "positioningQualityReasonCode": "POSITIONING_QUALITY_NOT_PROVEN",
            "positioningQualityExecutionAllowed": False,
        }
        _write_run(self.tmp, WALL, RUN_A, stages=stages)
        with self.assertRaises(ProductionStage3BindError) as ctx:
            resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)
        self.assertEqual(ctx.exception.code, REASON_GATES_NOT_PASS)

    def test_historical_sim3_missing_provenance_rejected_for_production(self) -> None:
        fingerprint = _write_run(self.tmp, WALL, RUN_A, sim3_extra={"wallId": None, "wallBuildRunId": None, "colmapModelFingerprint": None, "modelFingerprint": None})
        # rewrite sim3 without provenance keys
        sim3 = _sim3(wall_id=WALL, run_id=RUN_A, fingerprint=fingerprint)
        for key in ("wallId", "wallBuildRunId", "colmapModelFingerprint", "modelFingerprint"):
            del sim3[key]
        _write_json(wall_build_run_dir(self.tmp, WALL, RUN_A) / "metric_registration" / "S_wall_colmap.json", sim3)
        with self.assertRaises(ProductionStage3BindError) as ctx:
            resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)
        self.assertEqual(ctx.exception.code, REASON_SIM3_PROVENANCE_NOT_PROVEN)

    def test_29_no_cos_or_network_required(self) -> None:
        text = Path(ROOT / "offline" / "reference_matching" / "production_run.py").read_text(encoding="utf-8")
        for token in ("tencentcloud", "SecretId", "SecretKey", "put_object", "boto3"):
            self.assertNotIn(token, text)
        _write_run(self.tmp, WALL, RUN_A)
        resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)

    def test_30_no_routes_involved(self) -> None:
        _write_run(self.tmp, WALL, RUN_A)
        bind = resolve_production_stage3_inputs(self.tmp, WALL, RUN_A)
        self.assertFalse((bind.run_dir / "routes.json").exists())
        cli = (ROOT / "tools" / "rockvision.py").read_text(encoding="utf-8")
        self.assertIn("--run-id", cli)

    def test_cli_reference_match_accepts_run_id(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("rockvision_tools_cli_s3", ROOT / "tools" / "rockvision.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        from unittest.mock import patch

        with patch("offline.reference_matching.cli.run_reference_match", return_value=0) as fn:
            code = mod.main(["reference-match", WALL, "--run-id", RUN_A], root=self.tmp)
        self.assertEqual(code, 0)
        fn.assert_called_once()
        self.assertEqual(fn.call_args.kwargs.get("run_id") or fn.call_args[1].get("run_id"), RUN_A)


class DevelopmentFixtureByteIdentityTests(unittest.TestCase):
    def test_jiulongfeng_development_fixture_hashes_unchanged(self) -> None:
        manifest = ROOT / "ios" / "RockVision" / "Resources" / "DevelopmentFixture" / "manifest.json"
        descriptors = ROOT / "ios" / "RockVision" / "Resources" / "DevelopmentFixture" / "descriptors.bin"
        landmarks = ROOT / "ios" / "RockVision" / "Resources" / "DevelopmentFixture" / "landmarks.json"
        if not manifest.is_file() or not descriptors.is_file() or not landmarks.is_file():
            self.skipTest("DevelopmentFixture not present")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(sha256_file(descriptors), payload["descriptorsSha256"])
        self.assertEqual(sha256_file(landmarks), payload["landmarksSha256"])
        self.assertTrue(payload["developmentFixtureOnly"])
        self.assertTrue(payload["notAWallPackage"])


if __name__ == "__main__":
    unittest.main()
