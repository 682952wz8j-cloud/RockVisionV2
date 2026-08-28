from __future__ import annotations

import hashlib
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.ingestion.hashing import sha256_file
from offline.metric_registration.pipeline import register
from offline.stage2_selection.select import select_stage2_inputs
from offline.stage2_selection.sources import Stage2SelectedSources, sources_from_selection
from offline.testdata.ingestion.jpeg_exif import write_jpeg
from offline.wall_build.orchestrator import run_wall_build
from offline.wall_build.states import PHASE1_EXECUTABLE_STAGES, ReasonCode, Stage, StageStatus

EXPECTED_SCALE = 3.19764417024824
EXPECTED_MRK = "DJI_202608231218_006_九龙峰/DJI_20260823122214_0002_D.MRK"
EXPECTED_META = "九龙峰森林站大楼/models/pc/0/terra_ply/metadata.xml"
EXPECTED_CAPTURE_DIR = "DJI_202608231218_006_九龙峰"
EXPECTED_SRS = "EPSG:32650"
EXPECTED_ORIGIN = [597786.85842445458, 3333597.1281958264, 352.50399999973473]
HEIGHT_SFM = "九龙峰森林站大楼/AT/sfm_geo_desc.json"
HEIGHT_LEGACY_MRK = "dji_flight_raw_jiulongfeng/rtk_ppk_004/DJI_20260812152955_0002_D.MRK"


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


def frozen_fingerprints() -> dict[str, str]:
    return {
        "incoming": _fingerprint(ROOT / "incoming" / "wall_jiulongfeng_01"),
        "colmap": _fingerprint(ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "colmap"),
        "metric": _fingerprint(ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "metric_registration"),
        "validation": _fingerprint(ROOT / "validation"),
        "gate5a": _fingerprint(ROOT / "validation" / "gate5a"),
    }


def _load_cli():
    path = ROOT / "tools" / "rockvision.py"
    spec = importlib.util.spec_from_file_location("rockvision_tools_cli_stage2", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class Stage2RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fp_before = frozen_fingerprints()

    def tearDown(self) -> None:
        self.assertEqual(frozen_fingerprints(), self.fp_before)

    def test_a1_selection_regression(self) -> None:
        incoming = ROOT / "incoming" / "wall_jiulongfeng_01"
        self.assertTrue(incoming.is_dir())
        artifact = select_stage2_inputs("wall_jiulongfeng_01", ROOT)
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS", artifact.get("selectionReasonCodes"))
        selected = artifact["selectedCapture"]["memberRelativePaths"]
        expected_images = sorted(
            p.relative_to(incoming).as_posix()
            for p in (incoming / EXPECTED_CAPTURE_DIR).glob("*.JPG")
        )
        self.assertEqual(selected, expected_images)
        self.assertEqual(len(selected), 47)
        self.assertEqual(artifact["selectedMRKSource"]["relativePath"], EXPECTED_MRK)
        self.assertEqual(artifact["selectedModelSpatialMetadata"]["relativePath"], EXPECTED_META)
        self.assertEqual(artifact["selectedSRS"], EXPECTED_SRS)
        origin = artifact["selectedSRSOrigin"]
        self.assertAlmostEqual(origin[0], EXPECTED_ORIGIN[0], places=6)
        self.assertAlmostEqual(origin[1], EXPECTED_ORIGIN[1], places=6)
        self.assertAlmostEqual(origin[2], EXPECTED_ORIGIN[2], places=6)
        self.assertEqual(artifact["sourceChecksums"][EXPECTED_MRK], sha256_file(incoming / EXPECTED_MRK))
        self.assertEqual(artifact["sourceChecksums"][EXPECTED_META], sha256_file(incoming / EXPECTED_META))
        self.assertEqual(artifact["outputFrame"], "WallLocal")
        self.assertEqual(artifact["wallMetricMetersProvenance"], "NOT_CLAIMED")
        self.assertNotIn("WallMetricMeters", artifact["outputFrame"])
        self.assertFalse(any("dji_20260823" == g.get("requiredSession") for g in artifact["captureGroups"]))

    def test_a2_metric_regression(self) -> None:
        try:
            import pycolmap  # noqa: F401
        except ImportError:
            self.fail("pycolmap is required for A2 metric regression")
        artifact = select_stage2_inputs("wall_jiulongfeng_01", ROOT)
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        sources = sources_from_selection(artifact)
        self.assertIsNotNone(sources)
        sources = Stage2SelectedSources(
            **{
                **sources.__dict__,
                "height_sfm_geo_desc": HEIGHT_SFM,
                "height_legacy_mrk": HEIGHT_LEGACY_MRK,
            }
        )
        dest = Path(tempfile.mkdtemp(prefix="rv_s2_a2_")) / "metric_registration"
        try:
            payload = register(
                "wall_jiulongfeng_01",
                ROOT,
                sources=sources,
                dest=dest,
                colmap_dir=ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "colmap",
            )
            self.assertAlmostEqual(payload["scale"], EXPECTED_SCALE, places=9)
            self.assertEqual(payload["outputFrame"], "WallLocal")
            self.assertEqual(payload["wallMetricMetersProvenance"], "NOT_CLAIMED")
            self.assertEqual(payload["originCompatibility"]["semantics"], "SPATIAL_SANITY_CHECK")
            self.assertFalse(payload["originCompatibility"]["isCaptureModelProvenanceProof"])
            self.assertNotIn("expectedHoldout", payload.get("holdoutRule") or {})
        finally:
            shutil.rmtree(dest.parent, ignore_errors=True)

    def test_production_build_remains_blocked(self) -> None:
        self.assertEqual(
            PHASE1_EXECUTABLE_STAGES,
            frozenset({Stage.DISCOVERY, Stage.PREFLIGHT, Stage.INGEST, Stage.QUALIFY}),
        )
        tmp = Path(tempfile.mkdtemp(prefix="rv_s2_build_"))
        wall = tmp / "incoming" / "wall_test_stage2_build"
        wall.mkdir(parents=True)
        write_jpeg(wall / "cam.jpg", with_gps=True)
        try:
            with patch("offline.colmap.cli.run_reconstruct") as recon, patch(
                "offline.metric_registration.cli.run_register"
            ) as reg:
                report = run_wall_build("wall_test_stage2_build", tmp)
            recon.assert_not_called()
            reg.assert_not_called()
            recon_status = report["stageStatuses"]["RECONSTRUCTION"]
            self.assertFalse(recon_status["executionAllowed"])
            self.assertEqual(recon_status["reasonCode"], ReasonCode.GENERIC_STAGE2_NOT_APPROVED.value)
            self.assertEqual(recon_status["status"], StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value)
            self.assertEqual(report["nextStage"], "RECONSTRUCTION")
            self.assertEqual(report["nextStageStatus"], StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_stage2_dev_cli_is_not_build(self) -> None:
        cli = _load_cli()
        self.assertTrue(hasattr(cli, "main"))
        source = (ROOT / "tools" / "rockvision.py").read_text(encoding="utf-8")
        self.assertIn("stage2-dev", source)
        self.assertIn("DEVELOPMENT ONLY", source)
        capability = (ROOT / "offline" / "wall_build" / "capability.py").read_text(encoding="utf-8")
        self.assertIn("GENERIC_STAGE2_NOT_APPROVED", capability)
        states = (ROOT / "offline" / "wall_build" / "states.py").read_text(encoding="utf-8")
        self.assertIn("PHASE1_EXECUTABLE_STAGES", states)
        self.assertNotIn("Stage.RECONSTRUCTION", states.split("PHASE1_EXECUTABLE_STAGES")[1].split(")")[0])


if __name__ == "__main__":
    unittest.main()
