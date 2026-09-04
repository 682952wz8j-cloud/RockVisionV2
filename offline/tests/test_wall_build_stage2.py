from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.stage2_capability import (
    GENERIC_STAGE2_PASS,
    PRODUCTION_BUILD_STAGE2_ENABLED,
    REMAINING_GENERIC_STAGE2_CORRECTNESS_BLOCKERS,
)
from offline.stage2_selection.sources import Stage2SelectedSources
from offline.testdata.ingestion.jpeg_exif import write_jpeg
from offline.wall_build.invocations import INVOKED, reset as reset_invocations
from offline.wall_build.orchestrator import run_wall_build
from offline.wall_build.states import ReasonCode, Stage, StageStatus


def _fingerprint(path: Path) -> str:
    if not path.exists():
        return "missing"
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(path).as_posix().encode("utf-8")
        stat = item.stat()
        digest.update(rel)
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()


def _sources(wall_id: str = "wall_test_stage2_prod") -> Stage2SelectedSources:
    return Stage2SelectedSources(
        wall_id=wall_id,
        image_relative_paths=("flight/a.jpg", "flight/b.jpg"),
        image_dir_relative="flight",
        mrk_relative_path="flight/x.MRK",
        metadata_xml_relative_path="export/terra_ply/metadata.xml",
        srs="EPSG:32650",
        srs_origin=(100.0, 200.0, 10.0),
        ply_relative_path=None,
        association_method="test",
        association_rule="test",
        height_provenance_evidence={
            "referenceEllipsoid": "WGS84",
            "referenceEllipsoidProvenanceStatus": "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC",
            "specDefaultInvoked": True,
            "mrkEllhValid": True,
            "heightObservationSemantic": "GNSS_GEODETIC_ELLIPSOIDAL_HEIGHT",
            "terraVerticalMode": "DEFAULT",
            "geoidConversionConfigured": "NO",
            "verticalOverrideConfigured": "NO",
            "usedSrsOrigin": [100.0, 200.0, 10.0],
            "selectedSrsOrigin": [100.0, 200.0, 10.0],
            "selectedMetadataRelativePath": "export/terra_ply/metadata.xml",
            "usedMetadataRelativePath": "export/terra_ply/metadata.xml",
            "terraExportRootRelative": "export",
            "srsOriginProvenanceOk": True,
        },
    )


def _pass_height(_incoming, _sources):
    return {
        "heightGateExecutionAllowed": True,
        "heightVerticalDatumProvenance": "AUTO_PASS",
        "reasonCode": "HEIGHT_APPROVED",
    }


def _pass_pq(_incoming, _sources):
    return {
        "positioningQualityExecutionAllowed": True,
        "positioningQualityProvenance": "AUTO_PASS",
        "positioningQualityReasonCode": "POSITIONING_QUALITY_FIXED_RTK",
        "selectedFrameCount": 2,
        "fixedFrameCount": 2,
        "nonFixedFrameCount": 0,
        "missingOrUnparseableFrameCount": 0,
    }


def _pass_recon(wall_id, root, *, sources=None, dest=None):
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "colmap_source_identity.json").write_text("{}\n", encoding="utf-8")
    return {
        "gateResult": "PASS",
        "sourceImages": 2,
        "registeredImages": 2,
        "selectedModelRelativePath": "sparse/best",
        "sources": sources,
    }


def _pass_register(wall_id, root, *, sources=None, dest=None, colmap_dir=None, run_id=None):
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "S_wall_colmap.json").write_text("{}\n", encoding="utf-8")
    return {
        "gateResult": "PASS",
        "validationStatus": "VALIDATED",
        "scale": 1.23,
        "correspondenceCount": 2,
        "holdoutMetrics": {"count": 1, "median": 0.01},
        "outputFrame": "WallLocal",
        "wallMetricMetersProvenance": "NOT_CLAIMED",
        "colmapSourceIdentityReasonCode": "COLMAP_SOURCE_IDENTITY_PROVEN",
        "colmapSourceIdentityExecutionAllowed": True,
        "sources": sources,
        "colmap_dir": colmap_dir,
    }


class WallBuildStage2ProductionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_wb_s2_"))
        (self.tmp / "incoming").mkdir(parents=True)
        self.wall_id = "wall_test_stage2_prod"
        wall = self.tmp / "incoming" / self.wall_id
        wall.mkdir(parents=True)
        write_jpeg(wall / "cam.jpg", with_gps=True)
        reset_invocations()
        self.bound_sources = _sources(self.wall_id)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_mocked(
        self,
        *,
        reconstruct=_pass_recon,
        register=_pass_register,
        height=_pass_height,
        positioning=_pass_pq,
        sources=None,
    ):
        sources = sources or self.bound_sources
        with (
            patch("offline.wall_build.stage2_run.select_stage2_inputs", return_value={"selectionStatus": "AUTO_PASS", "selectedCapture": {"memberRelativePaths": list(sources.image_relative_paths)}}),
            patch("offline.wall_build.stage2_run.sources_from_selection", return_value=sources) as src_fn,
            patch("offline.wall_build.stage2_run.evaluate_generic_height_from_sources", side_effect=height),
            patch("offline.wall_build.stage2_run.evaluate_positioning_quality_from_sources", side_effect=positioning),
            patch("offline.wall_build.stage2_run.reconstruct", side_effect=reconstruct) as recon,
            patch("offline.wall_build.stage2_run.register", side_effect=register) as reg,
            patch("offline.reference_matching.cli.run_reference_match") as match,
            patch("offline.pnp.cli.run_pnp") as pnp,
        ):
            report = run_wall_build(self.wall_id, self.tmp)
        return report, recon, reg, src_fn, match, pnp

    def test_a_production_permits_reconstruction(self) -> None:
        self.assertTrue(GENERIC_STAGE2_PASS)
        self.assertTrue(PRODUCTION_BUILD_STAGE2_ENABLED)
        self.assertEqual(REMAINING_GENERIC_STAGE2_CORRECTNESS_BLOCKERS, 0)
        report, recon, _reg, _src, _match, _pnp = self._run_mocked()
        self.assertTrue(report["stageStatuses"]["RECONSTRUCTION"]["invoked"])
        self.assertEqual(report["stageStatuses"]["RECONSTRUCTION"]["status"], StageStatus.AUTO_PASS.value)
        recon.assert_called_once()
        self.assertIn("RECONSTRUCTION", report["executableStageAllowlist"])

    def test_b_production_permits_metric_registration(self) -> None:
        report, _recon, reg, _src, _match, _pnp = self._run_mocked()
        self.assertTrue(report["stageStatuses"]["METRIC_REGISTRATION"]["invoked"])
        self.assertEqual(report["stageStatuses"]["METRIC_REGISTRATION"]["status"], StageStatus.AUTO_PASS.value)
        reg.assert_called_once()
        self.assertIn("METRIC_REGISTRATION", report["executableStageAllowlist"])
        self.assertEqual(reg.call_args.kwargs.get("run_id"), Path(report["runOutputDir"]).name)

    def test_c_uses_sources_from_selection(self) -> None:
        _report, _recon, _reg, src_fn, _match, _pnp = self._run_mocked()
        src_fn.assert_called_once()

    def test_d_does_not_call_legacy_reconstruct_register_path(self) -> None:
        _report, recon, reg, _src, _match, _pnp = self._run_mocked()
        self.assertIsNotNone(recon.call_args.kwargs.get("sources"))
        self.assertIsNotNone(reg.call_args.kwargs.get("sources"))
        self.assertFalse(_report["stageStatuses"]["RECONSTRUCTION"].get("legacyPathUsed"))
        self.assertFalse(_report["stageStatuses"]["METRIC_REGISTRATION"].get("legacyPathUsed"))

    def test_e_same_selected_sources_bind_reconstruction_and_registration(self) -> None:
        _report, recon, reg, _src, _match, _pnp = self._run_mocked()
        self.assertIs(recon.call_args.kwargs["sources"], self.bound_sources)
        self.assertIs(reg.call_args.kwargs["sources"], self.bound_sources)
        self.assertEqual(recon.call_args.kwargs["dest"], reg.call_args.kwargs["colmap_dir"])

    def test_f_positioning_failure_prevents_reconstruction(self) -> None:
        def fail_pq(_incoming, _sources):
            return {
                "positioningQualityExecutionAllowed": False,
                "positioningQualityProvenance": "DEVELOPMENT_GATE_REVIEW_REQUIRED",
                "positioningQualityReasonCode": "POSITIONING_QUALITY_NOT_PROVEN",
                "selectedFrameCount": 2,
                "fixedFrameCount": 0,
                "nonFixedFrameCount": 2,
                "missingOrUnparseableFrameCount": 0,
            }

        report, recon, reg, _src, _match, _pnp = self._run_mocked(positioning=fail_pq)
        recon.assert_not_called()
        reg.assert_not_called()
        self.assertNotIn("reconstruct", INVOKED)
        self.assertEqual(report["stageStatuses"]["POSITIONING_QUALITY"]["reasonCode"], "POSITIONING_QUALITY_NOT_PROVEN")
        self.assertEqual(report["stageStatuses"]["RECONSTRUCTION"]["status"], StageStatus.BLOCKED.value)
        self.assertFalse(report["stageStatuses"]["RECONSTRUCTION"].get("invoked"))
        self.assertTrue(report["productionBuildStage2Enabled"])

    def test_g_identity_failure_prevents_metric_fit(self) -> None:
        def fail_register(wall_id, root, *, sources=None, dest=None, colmap_dir=None, run_id=None):
            dest.mkdir(parents=True, exist_ok=True)
            return {
                "gateResult": "DEVELOPMENT_GATE_REVIEW_REQUIRED",
                "validationStatus": "NOT VALIDATED",
                "correspondenceCount": 0,
                "reasonCode": "COLMAP_SOURCE_IDENTITY_NOT_PROVEN",
                "colmapSourceIdentityReasonCode": "COLMAP_SOURCE_IDENTITY_NOT_PROVEN",
                "colmapSourceIdentityExecutionAllowed": False,
            }

        report, recon, reg, _src, _match, _pnp = self._run_mocked(register=fail_register)
        recon.assert_called_once()
        reg.assert_called_once()
        self.assertEqual(report["stageStatuses"]["METRIC_REGISTRATION"]["reasonCode"], "COLMAP_SOURCE_IDENTITY_NOT_PROVEN")
        self.assertFalse(report["stageStatuses"]["METRIC_REGISTRATION"].get("sWallColmapWritten"))
        self.assertFalse((Path(report["runOutputDir"]) / "metric_registration" / "S_wall_colmap.json").is_file())

    def test_h_input_mutation_terminates_run(self) -> None:
        import offline.ingestion.pipeline as ingest_mod

        real_ingest = ingest_mod.ingest

        def mutate_then_ingest(wall_id, root):
            summary = real_ingest(wall_id, root)
            (root / "incoming" / wall_id / "cam.jpg").write_bytes(b"changed-bytes")
            return summary

        with (
            patch("offline.wall_build.orchestrator.ingest", side_effect=mutate_then_ingest),
            patch("offline.wall_build.stage2_run.reconstruct") as recon,
        ):
            report = run_wall_build(self.wall_id, self.tmp)
        recon.assert_not_called()
        self.assertEqual(report["runTerminalStatus"], "AUTO_FAIL")
        self.assertIn(ReasonCode.INPUT_MUTATED_DURING_RUN.value, report["reasonCodes"])

    def test_l_downstream_stage3_and_routes_remain_blocked(self) -> None:
        report, _recon, _reg, _src, match, pnp = self._run_mocked()
        match.assert_not_called()
        pnp.assert_not_called()
        self.assertNotIn("reference-match", INVOKED)
        self.assertNotIn("pnp", INVOKED)
        for stage in ("REGISTER", "REFERENCE_MATCH", "PNP", "REFERENCE_MAP", "ROUTE_COORDINATE_REGISTRATION", "ROUTE_PACKAGE_BUILD"):
            self.assertEqual(report["stageStatuses"][stage]["status"], StageStatus.BLOCKED.value, stage)
            self.assertFalse(report["stageStatuses"][stage].get("invoked"))
        self.assertFalse(report["fieldTestReady"])
        self.assertEqual(report["forbiddenCommandsNotInvoked"], ["reference-match", "pnp"])

    def test_m_no_wall_metric_meters_claim(self) -> None:
        report, _recon, _reg, _src, _match, _pnp = self._run_mocked()
        self.assertEqual(report["stageStatuses"]["METRIC_REGISTRATION"]["wallMetricMetersProvenance"], "NOT_CLAIMED")
        self.assertEqual(report["stageStatuses"]["METRIC_REGISTRATION"]["outputFrame"], "WallLocal")

    def test_terra_ply_product_is_frozen_into_run_dest(self) -> None:
        report, *_ = self._run_mocked()
        dest = Path(report["runOutputDir"])
        freeze_path = dest / "terra_ply_product.json"
        self.assertTrue(freeze_path.is_file())
        payload = json.loads(freeze_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["frozen"])
        self.assertTrue(payload["terraProductProvenanceRecorded"])
        self.assertEqual(payload["schemaVersion"], "terra_ply_product.1")

    def test_n_no_jiulongfeng_wall_id_special_branch(self) -> None:
        text = (ROOT / "offline" / "wall_build" / "stage2_run.py").read_text(encoding="utf-8")
        self.assertNotIn("wall_jiulongfeng_01", text)
        self.assertNotIn("wall_jinshidong_01", text)
        self.assertNotIn("DJI_CAPTURE_DIR", text)
        self.assertNotIn("REQUIRED_SESSION", text)
        self.assertNotIn("dji_20260823", text)


class WallBuildStage2RealRegressionTests(unittest.TestCase):
    def test_j_jinshidong_fail_closed_before_reconstruction(self) -> None:
        incoming = ROOT / "incoming" / "wall_jinshidong_01"
        if not incoming.is_dir():
            self.skipTest("incoming/wall_jinshidong_01 not present")
        reset_invocations()
        with (
            patch("offline.wall_build.stage2_run.reconstruct") as recon,
            patch("offline.wall_build.stage2_run.register") as reg,
        ):
            report = run_wall_build("wall_jinshidong_01", ROOT)
        recon.assert_not_called()
        reg.assert_not_called()
        self.assertNotIn("reconstruct", INVOKED)
        self.assertTrue(report["productionBuildStage2Enabled"])
        self.assertTrue(report["genericStage2Pass"])
        pq = report["stageStatuses"]["POSITIONING_QUALITY"]
        self.assertEqual(pq["reasonCode"], "POSITIONING_QUALITY_NOT_PROVEN")
        self.assertFalse(pq.get("positioningQualityExecutionAllowed"))
        self.assertEqual(pq.get("fixedFrameCount"), 0)
        self.assertEqual(pq.get("selectedFrameCount"), 179)
        self.assertEqual(pq.get("nonFixedFrameCount"), 152)
        self.assertEqual(pq.get("missingOrUnparseableFrameCount"), 27)
        self.assertEqual(report["stageStatuses"]["RECONSTRUCTION"]["status"], StageStatus.BLOCKED.value)
        self.assertFalse(report["stageStatuses"]["RECONSTRUCTION"].get("invoked"))
        dest = Path(report["runOutputDir"])
        self.assertFalse((dest / "colmap").exists() and any((dest / "colmap").rglob("images.bin")))
        self.assertFalse((dest / "metric_registration" / "S_wall_colmap.json").exists())
        print(
            "JINSHIDONG_PRODUCTION_BUILD_SUMMARY "
            f"runId={report.get('runId')} "
            f"terminal={report.get('runTerminalStatus')} "
            f"pq={pq.get('reasonCode')} "
            f"reconstructInvoked={report['stageStatuses']['RECONSTRUCTION'].get('invoked')}"
        )

    def test_i_jiulongfeng_production_build_positive(self) -> None:
        incoming = ROOT / "incoming" / "wall_jiulongfeng_01"
        if not incoming.is_dir():
            self.skipTest("incoming/wall_jiulongfeng_01 not present")
        frozen_colmap = ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "colmap"
        frozen_metric = ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "metric_registration"
        before = {
            "incoming": _fingerprint(incoming),
            "colmap": _fingerprint(frozen_colmap),
            "metric": _fingerprint(frozen_metric),
        }
        reset_invocations()
        report = run_wall_build("wall_jiulongfeng_01", ROOT)
        self.assertEqual(_fingerprint(incoming), before["incoming"])
        self.assertEqual(_fingerprint(frozen_colmap), before["colmap"])
        self.assertEqual(_fingerprint(frozen_metric), before["metric"])
        self.assertTrue(report["productionBuildStage2Enabled"])
        self.assertTrue(report["genericStage2Pass"])
        self.assertEqual(report["stageStatuses"]["DISCOVERY"]["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(report["stageStatuses"]["PREFLIGHT"]["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(report["stageStatuses"]["INGEST"]["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(report["stageStatuses"]["QUALIFY"]["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(report["stageStatuses"]["STAGE2_SELECTION"]["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(report["stageStatuses"]["HEIGHT_VERTICAL_DATUM"]["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(report["stageStatuses"]["POSITIONING_QUALITY"]["status"], StageStatus.AUTO_PASS.value)
        recon = report["stageStatuses"]["RECONSTRUCTION"]
        metric = report["stageStatuses"]["METRIC_REGISTRATION"]
        if recon.get("status") != StageStatus.AUTO_PASS.value:
            self.fail(
                "REAL_RECONSTRUCTION_BLOCKED production reconstruct "
                f"status={recon.get('status')} gate={recon.get('gateResult')} "
                f"reason={recon.get('reasonCode')}"
            )
        if metric.get("status") != StageStatus.AUTO_PASS.value:
            self.fail(
                "REAL_RECONSTRUCTION_BLOCKED production register "
                f"status={metric.get('status')} gate={metric.get('gateResult')} "
                f"validation={metric.get('validationStatus')} reason={metric.get('reasonCode')}"
            )
        dest = Path(report["runOutputDir"])
        self.assertTrue((dest / "colmap" / "colmap_source_identity.json").is_file())
        self.assertTrue((dest / "metric_registration" / "S_wall_colmap.json").is_file())
        self.assertTrue((dest / "stage2_input_selection.json").is_file())
        identity = json.loads((dest / "colmap" / "colmap_source_identity.json").read_text(encoding="utf-8"))
        self.assertEqual(identity.get("provenanceOrigin"), "RECONSTRUCTION_RUN")
        self.assertEqual(identity.get("selectedImageCount"), 47)
        self.assertEqual(metric.get("outputFrame"), "WallLocal")
        self.assertEqual(metric.get("wallMetricMetersProvenance"), "NOT_CLAIMED")
        self.assertEqual(metric.get("colmapSourceIdentityReasonCode"), "COLMAP_SOURCE_IDENTITY_PROVEN")
        self.assertEqual(report["stageStatuses"]["REFERENCE_MATCH"]["status"], StageStatus.BLOCKED.value)
        self.assertFalse(report["fieldTestReady"])
        print(
            "JIULONGFENG_PRODUCTION_BUILD_SUMMARY "
            f"runId={report.get('runId')} "
            f"selected={report['stageStatuses']['STAGE2_SELECTION'].get('selectedImageCount')} "
            f"registered={recon.get('registeredImages')} "
            f"model={recon.get('selectedModelRelativePath')} "
            f"identity={metric.get('colmapSourceIdentityReasonCode')} "
            f"correspondenceCount={metric.get('correspondenceCount')} "
            f"gate={metric.get('gateResult')} "
            f"validation={metric.get('validationStatus')} "
            f"scale={metric.get('scale')} "
            f"holdout={metric.get('holdoutMetrics')}"
        )


if __name__ == "__main__":
    unittest.main()
