from __future__ import annotations

import hashlib
import importlib.util
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

from offline.ingestion.hashing import sha256_file
from offline.testdata.ingestion.jpeg_exif import write_jpeg
from offline.wall_build.invocations import INVOKED, reset as reset_invocations
from offline.wall_build.orchestrator import resolve_terminal_status, run_wall_build
from offline.wall_build.states import ReasonCode, RunTerminalStatus, Stage, StageStatus

DXF_OK = """  0
SECTION
  2
HEADER
  0
ENDSEC
  0
SECTION
  2
ENTITIES
  0
POLYLINE
  0
VERTEX
 10
0.0
 20
0.0
 30
0.0
  0
VERTEX
 10
1.0
 20
0.0
 30
0.0
  0
SEQEND
  0
ENDSEC
  0
EOF
"""


def _write(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")


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


def _load_cli():
    path = ROOT / "tools" / "rockvision.py"
    spec = importlib.util.spec_from_file_location("rockvision_tools_cli", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class WallBuildPhase1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.protected = {
            "gate5a": _fingerprint(ROOT / "validation" / "gate5a"),
            "jf_incoming": _fingerprint(ROOT / "incoming" / "wall_jiulongfeng_01"),
            "jf_colmap": _fingerprint(ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "colmap"),
            "jf_metric": _fingerprint(ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "metric_registration"),
        }

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_wall_build_"))
        (self.tmp / "incoming").mkdir(parents=True)
        (self.tmp / "offline" / "work").mkdir(parents=True)
        reset_invocations()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wall(self, wall_id: str = "wall_test_phase1_ok") -> Path:
        path = self.tmp / "incoming" / wall_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _build(self, wall_id: str = "wall_test_phase1_ok"):
        with (
            patch("offline.wall_build.stage2_run.reconstruct") as reconstruct,
            patch("offline.wall_build.stage2_run.register") as register,
            patch("offline.reference_matching.cli.run_reference_match") as match,
            patch("offline.pnp.cli.run_pnp") as pnp,
        ):
            report = run_wall_build(wall_id, self.tmp)
        reconstruct.assert_not_called()
        register.assert_not_called()
        match.assert_not_called()
        pnp.assert_not_called()
        self.assertNotIn("reconstruct", INVOKED)
        self.assertNotIn("register", INVOKED)
        self.assertNotIn("reference-match", INVOKED)
        self.assertNotIn("pnp", INVOKED)
        self.assertFalse((self.tmp / "incoming" / wall_id / "routes.json").exists())
        work = self.tmp / "offline" / "work" / wall_id
        self.assertFalse((work / "routes.json").exists())
        return report

    def test_cli_dispatch_and_valid_wall_id(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "DJI_0001.JPG")
        cli = _load_cli()
        code = cli.main(["build", "wall_test_phase1_ok"], root=self.tmp)
        self.assertEqual(code, 1)
        report_paths = list((self.tmp / "offline" / "work" / "wall_test_phase1_ok" / "wall_build").glob("*/wall_build_report.json"))
        self.assertEqual(len(report_paths), 1)
        report = json.loads(report_paths[0].read_text(encoding="utf-8"))
        self.assertEqual(report["wallId"], "wall_test_phase1_ok")
        self.assertEqual(report["runTerminalStatus"], RunTerminalStatus.AUTO_FAIL.value)
        self.assertEqual(report["stageStatuses"]["STAGE2_SELECTION"]["reasonCode"], ReasonCode.STAGE2_SELECTION_NOT_AUTO_PASS.value)
        self.assertTrue(report["productionBuildStage2Enabled"])

    def test_invalid_wall_id(self) -> None:
        report = self._build("jinshidong")
        self.assertEqual(report["runTerminalStatus"], RunTerminalStatus.AUTO_FAIL.value)
        self.assertIn(ReasonCode.INVALID_WALL_ID.value, report["reasonCodes"])
        self.assertTrue(Path(report["runOutputDir"]).as_posix().endswith("/_phase1_rejected/wall_build/" + report["runId"]) or "_phase1_rejected" in report["runOutputDir"])

    def test_unsafe_wall_path(self) -> None:
        report = self._build("../etc")
        self.assertEqual(report["runTerminalStatus"], RunTerminalStatus.AUTO_FAIL.value)
        self.assertIn(ReasonCode.UNSAFE_WALL_PATH.value, report["reasonCodes"])

    def test_missing_wall_directory(self) -> None:
        report = self._build("wall_test_phase1_missing")
        self.assertEqual(report["runTerminalStatus"], RunTerminalStatus.AUTO_FAIL.value)
        self.assertIn(ReasonCode.MISSING_WALL_DIRECTORY.value, report["reasonCodes"])
        self.assertEqual(report["stageStatuses"]["DISCOVERY"]["status"], StageStatus.AUTO_FAIL.value)

    def test_recursive_discovery_nested_unicode_and_all_dxf(self) -> None:
        wall = self._wall("wall_test_phase1_nested")
        nested = wall / "arbitrary_nested_folder" / "DJI_flight"
        write_jpeg(nested / "DJI_0001.JPG")
        _write(wall / "飞翔的石头.dxf", DXF_OK)
        _write(wall / "36号线.dxf", DXF_OK)
        _write(wall / "左侧项目线.dxf", DXF_OK)
        _write(wall / "notes.bin", b"\x00\x01UNKNOWN")
        report = self._build("wall_test_phase1_nested")
        names = {item["sourceFilename"] for item in report["dxfFiles"]}
        self.assertEqual(names, {"飞翔的石头.dxf", "36号线.dxf", "左侧项目线.dxf"})
        self.assertEqual(len(report["dxfFiles"]), 3)
        self.assertEqual(report["discoveredFileCount"], 5)
        self.assertTrue(report["ignoredUnknownFiles"])
        self.assertEqual(report["ignoredUnknownFiles"][0]["classification"], ReasonCode.IGNORED_UNKNOWN_FILE.value)
        self.assertEqual(report["stageStatuses"]["DISCOVERY"]["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(report["stageStatuses"]["STAGE2_SELECTION"]["reasonCode"], ReasonCode.STAGE2_SELECTION_NOT_AUTO_PASS.value)
        self.assertNotEqual(report["runTerminalStatus"], RunTerminalStatus.HUMAN_REVIEW_REQUIRED.value)

    def test_unknown_file_does_not_fail_run(self) -> None:
        wall = self._wall("wall_test_phase1_unknown")
        write_jpeg(wall / "cam.jpg")
        _write(wall / "weird.dat", b"\xff\x00not classified")
        report = self._build("wall_test_phase1_unknown")
        self.assertEqual(report["stageStatuses"]["DISCOVERY"]["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(report["stageStatuses"]["INGEST"]["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(report["stageStatuses"]["STAGE2_SELECTION"]["reasonCode"], ReasonCode.STAGE2_SELECTION_NOT_AUTO_PASS.value)
        self.assertNotEqual(report["runTerminalStatus"], RunTerminalStatus.HUMAN_REVIEW_REQUIRED.value)

    def test_zero_byte_recognized_is_warning_not_run_fail(self) -> None:
        wall = self._wall("wall_test_phase1_zerobyte")
        write_jpeg(wall / "good.jpg")
        _write(wall / "empty.jpg", b"")
        report = self._build("wall_test_phase1_zerobyte")
        self.assertIn(ReasonCode.ZERO_BYTE_RECOGNIZED_INPUT.value, report["warnings"])
        self.assertEqual(report["stageStatuses"]["PREFLIGHT"]["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(report["stageStatuses"]["STAGE2_SELECTION"]["reasonCode"], ReasonCode.STAGE2_SELECTION_NOT_AUTO_PASS.value)
        self.assertNotEqual(report["runTerminalStatus"], RunTerminalStatus.HUMAN_REVIEW_REQUIRED.value)

    def test_corrupt_dxf_fails_preflight_and_run(self) -> None:
        wall = self._wall("wall_test_phase1_dxf")
        write_jpeg(wall / "cam.jpg")
        _write(wall / "飞翔的石头.dxf", DXF_OK)
        _write(wall / "broken.dxf", "this is not a dxf file\n")
        report = self._build("wall_test_phase1_dxf")
        by_name = {item["sourceFilename"]: item for item in report["dxfFiles"]}
        self.assertEqual(by_name["飞翔的石头.dxf"]["parseStatus"], StageStatus.AUTO_PASS.value)
        self.assertEqual(by_name["broken.dxf"]["parseStatus"], StageStatus.AUTO_FAIL.value)
        self.assertEqual(by_name["broken.dxf"]["reasonCode"], ReasonCode.CORRUPT_DXF.value)
        self.assertEqual(report["stageStatuses"]["PREFLIGHT"]["status"], StageStatus.AUTO_FAIL.value)
        self.assertEqual(report["stageStatuses"]["PREFLIGHT"]["reasonCode"], ReasonCode.CORRUPT_DXF.value)
        self.assertEqual(report["stageStatuses"]["INGEST"]["status"], StageStatus.BLOCKED.value)
        self.assertEqual(report["stageStatuses"]["QUALIFY"]["status"], StageStatus.BLOCKED.value)
        self.assertEqual(report["runTerminalStatus"], RunTerminalStatus.AUTO_FAIL.value)
        self.assertNotIn("ingest", INVOKED)
        self.assertNotIn("qualify", INVOKED)
        self.assertTrue(
            any("broken.dxf" in err for err in report["stageStatuses"]["PREFLIGHT"].get("checks", {}).get("corruptRouteGeometryFiles", []))
            or any("broken.dxf" in item for item in report.get("blockingEvidence") or [])
        )

    def test_zero_byte_dxf_fails_preflight(self) -> None:
        wall = self._wall("wall_test_phase1_zerobyte_dxf")
        write_jpeg(wall / "cam.jpg")
        _write(wall / "empty.dxf", b"")
        report = self._build("wall_test_phase1_zerobyte_dxf")
        self.assertEqual(report["stageStatuses"]["PREFLIGHT"]["status"], StageStatus.AUTO_FAIL.value)
        self.assertEqual(report["stageStatuses"]["PREFLIGHT"]["reasonCode"], ReasonCode.CORRUPT_DXF.value)
        self.assertEqual(report["runTerminalStatus"], RunTerminalStatus.AUTO_FAIL.value)
        self.assertEqual(report["stageStatuses"]["INGEST"]["status"], StageStatus.BLOCKED.value)
        self.assertNotIn("ingest", INVOKED)

    def test_input_manifest_sha256_and_run_id(self) -> None:
        wall = self._wall("wall_test_phase1_manifest")
        jpeg = wall / "cam.jpg"
        write_jpeg(jpeg)
        report_a = self._build("wall_test_phase1_manifest")
        manifest_path = Path(report_a["inputManifest"]["path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["wallId"], "wall_test_phase1_manifest")
        self.assertEqual(manifest["runId"], report_a["runId"])
        self.assertTrue(manifest["runId"].startswith("wb_"))
        rec = manifest["files"][0]
        self.assertEqual(rec["checksum"], sha256_file(jpeg))
        self.assertEqual(rec["fileSize"], jpeg.stat().st_size)
        self.assertEqual(rec["relativePath"], "cam.jpg")
        report_b = self._build("wall_test_phase1_manifest")
        self.assertNotEqual(report_a["runId"], report_b["runId"])
        self.assertEqual(report_a["wallId"], report_b["wallId"])

    def test_multiple_stage2_candidates_remain_inventory(self) -> None:
        wall = self._wall("wall_test_phase1_multi")
        write_jpeg(wall / "DJI_AAA" / "a.jpg")
        write_jpeg(wall / "DJI_BBB" / "b.jpg")
        _write(wall / "DJI_AAA" / "one.MRK", "1,Lat,2,Lon,3,Ellh\n")
        _write(wall / "DJI_BBB" / "two.MRK", "1,Lat,2,Lon,3,Ellh\n")
        _write(wall / "DJI_AAA" / "metadata.xml", "<xml/>")
        _write(wall / "DJI_BBB" / "metadata.xml", "<xml/>")
        _write(wall / "model_a.ply", "ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n")
        _write(wall / "model_b.ply", "ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n1 1 1\n")
        report = self._build("wall_test_phase1_multi")
        self.assertGreaterEqual(len(report["captureCandidates"]), 2)
        self.assertGreaterEqual(len(report["mrkCandidates"]), 2)
        self.assertGreaterEqual(len(report["metadataCandidates"]), 2)
        self.assertGreaterEqual(len(report["modelCandidates"]), 2)
        self.assertTrue(all(not c.get("selected") for c in report["captureCandidates"]))
        self.assertNotIn(RunTerminalStatus.HUMAN_REVIEW_REQUIRED.value, {s["status"] for s in report["stageStatuses"].values()})
        self.assertEqual(report["runTerminalStatus"], RunTerminalStatus.AUTO_FAIL.value)
        self.assertEqual(report["stageStatuses"]["STAGE2_SELECTION"]["reasonCode"], ReasonCode.STAGE2_SELECTION_NOT_AUTO_PASS.value)
        self.assertFalse(report["stageStatuses"]["RECONSTRUCTION"].get("invoked"))
        self.assertIn(ReasonCode.MULTIPLE_CAPTURE_CANDIDATES.value, report["warnings"])
        self.assertIn(ReasonCode.MULTIPLE_MRK_CANDIDATES.value, report["warnings"])
        self.assertIn(ReasonCode.MULTIPLE_METADATA_CANDIDATES.value, report["warnings"])
        self.assertIn(ReasonCode.MULTIPLE_MODEL_CANDIDATES.value, report["warnings"])

    def test_auto_pass_and_gate_boundary(self) -> None:
        wall = self._wall("wall_test_phase1_pass")
        write_jpeg(wall / "cam.jpg", with_gps=True)
        report = self._build("wall_test_phase1_pass")
        for stage in ("DISCOVERY", "PREFLIGHT", "INGEST", "QUALIFY"):
            self.assertEqual(report["stageStatuses"][stage]["status"], StageStatus.AUTO_PASS.value, stage)
        self.assertEqual(report["automationReached"], "QUALIFICATION_COMPLETE")
        self.assertEqual(report["nextStage"], "STAGE2_SELECTION")
        self.assertNotEqual(report["stageStatuses"]["STAGE2_SELECTION"]["status"], StageStatus.AUTO_PASS.value)
        recon = report["stageStatuses"]["RECONSTRUCTION"]
        self.assertFalse(recon.get("invoked"))
        self.assertEqual(recon["status"], StageStatus.BLOCKED.value)
        self.assertEqual(recon["reasonCode"], ReasonCode.UPSTREAM_STAGE_NOT_COMPLETE.value)
        self.assertEqual(report["stageStatuses"]["REGISTER"]["status"], StageStatus.BLOCKED.value)
        self.assertEqual(report["stageStatuses"]["REFERENCE_MATCH"]["status"], StageStatus.BLOCKED.value)
        self.assertEqual(report["stageStatuses"]["PNP"]["status"], StageStatus.BLOCKED.value)
        self.assertTrue(report["productionBuildStage2Enabled"])
        self.assertTrue(report["genericStage2Pass"])
        self.assertEqual(report["fieldTestReady"], False)
        self.assertEqual(report["fieldTestReadyLabel"], "NO")
        self.assertEqual(report["jinshidongUnattendedToFieldTestReady"], "NO")
        self.assertIsNone(report["efficiency"]["fieldAcquisitionDuration"])

    def test_ingest_pass_with_warnings_stays_auto_pass(self) -> None:
        wall = self._wall("wall_test_phase1_warn")
        write_jpeg(wall / "nogps.jpg", with_gps=False)
        report = self._build("wall_test_phase1_warn")
        ingest = report["stageStatuses"]["INGEST"]
        self.assertEqual(ingest["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(ingest["ingestResult"], "PASS WITH WARNINGS")
        self.assertTrue(ingest["warnings"])
        self.assertEqual(report["stageStatuses"]["STAGE2_SELECTION"]["reasonCode"], ReasonCode.STAGE2_SELECTION_NOT_AUTO_PASS.value)
        self.assertNotEqual(report["runTerminalStatus"], RunTerminalStatus.HUMAN_REVIEW_REQUIRED.value)

    def test_auto_fail_missing_images(self) -> None:
        wall = self._wall("wall_test_phase1_noimg")
        _write(wall / "readme.txt", "no photos")
        report = self._build("wall_test_phase1_noimg")
        self.assertEqual(report["runTerminalStatus"], RunTerminalStatus.AUTO_FAIL.value)
        self.assertEqual(report["stageStatuses"]["PREFLIGHT"]["status"], StageStatus.AUTO_FAIL.value)
        self.assertEqual(report["stageStatuses"]["PREFLIGHT"]["reasonCode"], ReasonCode.MISSING_REQUIRED_SOURCE_IMAGES.value)
        self.assertEqual(report["stageStatuses"]["INGEST"]["status"], StageStatus.BLOCKED.value)
        self.assertNotIn("ingest", INVOKED)
        self.assertEqual(report["stageStatuses"]["REGISTER"]["status"], StageStatus.BLOCKED.value)

    def test_human_review_enum_exists_but_has_no_production_trigger(self) -> None:
        terminal = resolve_terminal_status(
            {
                "DISCOVERY": {"status": StageStatus.AUTO_PASS.value},
                "REVIEW": {"status": StageStatus.HUMAN_REVIEW_REQUIRED.value, "reasonCode": "UNIT_TEST_ONLY"},
            },
            freeze_ok=True,
        )
        self.assertEqual(terminal, RunTerminalStatus.HUMAN_REVIEW_REQUIRED)
        wall = self._wall("wall_test_phase1_noreview")
        write_jpeg(wall / "cam.jpg")
        report = self._build("wall_test_phase1_noreview")
        self.assertNotEqual(report["runTerminalStatus"], RunTerminalStatus.HUMAN_REVIEW_REQUIRED.value)
        self.assertNotIn(StageStatus.HUMAN_REVIEW_REQUIRED.value, [s["status"] for s in report["stageStatuses"].values()])

    def test_qualify_incoming_unchanged_false_is_auto_fail(self) -> None:
        wall = self._wall("wall_test_phase1_mut_q")
        write_jpeg(wall / "cam.jpg")
        fake = {
            "result": "FAIL",
            "incomingUnchanged": False,
            "errors": ["incoming hashes changed during qualification"],
            "colmapReadiness": {"status": "NOT READY"},
        }
        with (
            patch("offline.wall_build.orchestrator.qualify", return_value=fake),
            patch("offline.wall_build.stage2_run.reconstruct") as reconstruct,
        ):
            report = run_wall_build("wall_test_phase1_mut_q", self.tmp)
        reconstruct.assert_not_called()
        self.assertEqual(report["stageStatuses"]["QUALIFY"]["status"], StageStatus.AUTO_FAIL.value)
        self.assertEqual(report["stageStatuses"]["QUALIFY"]["reasonCode"], ReasonCode.INPUT_MUTATED_DURING_RUN.value)
        self.assertEqual(report["runTerminalStatus"], RunTerminalStatus.AUTO_FAIL.value)
        self.assertNotEqual(report["runTerminalStatus"], RunTerminalStatus.HUMAN_REVIEW_REQUIRED.value)

    def test_input_mutation_detected(self) -> None:
        wall = self._wall("wall_test_phase1_mut")
        write_jpeg(wall / "cam.jpg")

        real_ingest = None
        import offline.ingestion.pipeline as ingest_mod

        real_ingest = ingest_mod.ingest

        def mutate_then_ingest(wall_id, root):
            summary = real_ingest(wall_id, root)
            (root / "incoming" / wall_id / "cam.jpg").write_bytes(b"changed-bytes")
            return summary

        with (
            patch("offline.wall_build.orchestrator.ingest", side_effect=mutate_then_ingest),
            patch("offline.wall_build.stage2_run.reconstruct") as reconstruct,
        ):
            report = run_wall_build("wall_test_phase1_mut", self.tmp)
        reconstruct.assert_not_called()
        self.assertEqual(report["runTerminalStatus"], RunTerminalStatus.AUTO_FAIL.value)
        self.assertIn(ReasonCode.INPUT_MUTATED_DURING_RUN.value, report["reasonCodes"])
        self.assertEqual(report["stageStatuses"]["INPUT_FREEZE"]["status"], StageStatus.AUTO_FAIL.value)

    def test_reports_written_and_no_wall_metric_claim(self) -> None:
        wall = self._wall("wall_test_phase1_report")
        write_jpeg(wall / "cam.jpg")
        _write(wall / "飞翔的石头.dxf", DXF_OK)
        report = self._build("wall_test_phase1_report")
        dest = Path(report["runOutputDir"])
        self.assertTrue((dest / "wall_build_report.json").is_file())
        self.assertTrue((dest / "wall_build_report.md").is_file())
        self.assertTrue((dest / "input_manifest.json").is_file())
        self.assertNotIn("incoming", dest.as_posix().split("/")[-5:])
        self.assertIn("/wall_build/", dest.as_posix())
        dxf = report["dxfFiles"][0]
        self.assertIsNone(dxf["coordinateFrame"])
        self.assertEqual(dxf["wallMetricMetersProvenance"], "NOT_CLAIMED")
        self.assertEqual(dxf["sourceFilename"], "飞翔的石头.dxf")

    def test_no_jinshidong_special_case_in_orchestrator(self) -> None:
        for path in (ROOT / "offline" / "wall_build").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn('wall == "wall_jinshidong_01"', text)
            self.assertNotIn("wall_jinshidong_01", text.replace("jinshidongUnattendedToFieldTestReady", ""))
            self.assertNotIn("work_tree_is_protected", text)
            self.assertNotIn("PROTECTED_WORK_WALL_IDS", text)
            self.assertNotIn("FROZEN_WORK_TREE_PROTECTED", text)
            self.assertNotIn("run_reconstruct", text)
            self.assertNotIn("run_register", text)
            self.assertNotIn("run_reference_match", text)
            self.assertNotIn("run_pnp", text)
            if path.name != "hard_bindings.py":
                self.assertNotIn("wall_jiulongfeng_01", text)

    def test_protected_artifacts_unchanged(self) -> None:
        self.assertEqual(_fingerprint(ROOT / "validation" / "gate5a"), self.protected["gate5a"])
        self.assertEqual(_fingerprint(ROOT / "incoming" / "wall_jiulongfeng_01"), self.protected["jf_incoming"])
        self.assertEqual(_fingerprint(ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "colmap"), self.protected["jf_colmap"])
        self.assertEqual(_fingerprint(ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "metric_registration"), self.protected["jf_metric"])

    def test_production_execution_policy_is_wall_agnostic(self) -> None:
        names = ("wall_test_phase1_equivalent", "wall_jiulongfeng_01")
        reports = {}
        for wall_id in names:
            reset_invocations()
            wall = self._wall(wall_id)
            write_jpeg(wall / "cam.jpg", with_gps=True)
            reports[wall_id] = self._build(wall_id)
            self.assertTrue(str(self.tmp) in reports[wall_id]["runOutputDir"])
            self.assertNotIn(str(ROOT / "incoming" / "wall_jiulongfeng_01"), reports[wall_id]["runOutputDir"])
            self.assertIn("ingest", INVOKED)
            self.assertIn("qualify", INVOKED)

        def policy(report: dict) -> dict:
            stages = report["stageStatuses"]
            recon = stages["RECONSTRUCTION"]
            return {
                "DISCOVERY": stages["DISCOVERY"]["status"],
                "PREFLIGHT": stages["PREFLIGHT"]["status"],
                "INGEST": (stages["INGEST"]["status"], stages["INGEST"].get("invoked")),
                "QUALIFY": (stages["QUALIFY"]["status"], stages["QUALIFY"].get("invoked")),
                "reconStatus": recon["status"],
                "reconExecutionAllowed": recon["executionAllowed"],
                "reconDeniedReason": recon["executionDeniedReason"],
                "reconReasonCode": recon["reasonCode"],
                "reconCapabilityStatus": recon.get("capabilityStatus"),
                "REGISTER": stages["REGISTER"]["status"],
                "REFERENCE_MATCH": stages["REFERENCE_MATCH"]["status"],
                "PNP": stages["PNP"]["status"],
                "automationReached": report["automationReached"],
                "nextStage": report["nextStage"],
                "nextStageStatus": report["nextStageStatus"],
                "nextStageReason": report["nextStageReason"],
                "terminal": report["runTerminalStatus"],
                "fieldTestReady": report["fieldTestReady"],
            }

        self.assertEqual(
            policy(reports["wall_test_phase1_equivalent"]),
            policy(reports["wall_jiulongfeng_01"]),
        )
        for wall_id, report in reports.items():
            with self.subTest(wall_id=wall_id):
                for stage in ("DISCOVERY", "PREFLIGHT", "INGEST", "QUALIFY"):
                    self.assertEqual(report["stageStatuses"][stage]["status"], StageStatus.AUTO_PASS.value)
                    self.assertTrue(report["stageStatuses"][stage].get("invoked"))
                recon = report["stageStatuses"]["RECONSTRUCTION"]
                self.assertFalse(recon.get("invoked"))
                self.assertEqual(recon["status"], StageStatus.BLOCKED.value)
                self.assertEqual(recon["reasonCode"], ReasonCode.UPSTREAM_STAGE_NOT_COMPLETE.value)
                self.assertFalse(recon["executionAllowed"])
                self.assertEqual(report["nextStage"], Stage.STAGE2_SELECTION.value)
                self.assertTrue(report["productionBuildStage2Enabled"])
                self.assertFalse(report["fieldTestReady"])

    def test_allowlist_recorded(self) -> None:
        wall = self._wall("wall_test_phase1_allow")
        write_jpeg(wall / "cam.jpg")
        report = self._build("wall_test_phase1_allow")
        self.assertEqual(
            set(report["executableStageAllowlist"]),
            {
                "DISCOVERY",
                "PREFLIGHT",
                "INGEST",
                "QUALIFY",
                "STAGE2_SELECTION",
                "HEIGHT_VERTICAL_DATUM",
                "POSITIONING_QUALITY",
                "RECONSTRUCTION",
                "METRIC_REGISTRATION",
            },
        )
        self.assertEqual(report["forbiddenCommandsNotInvoked"], ["reference-match", "pnp"])


if __name__ == "__main__":
    unittest.main()
