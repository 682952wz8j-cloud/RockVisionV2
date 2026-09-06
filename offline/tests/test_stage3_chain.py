from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.wall_build.stage3_run import GATE3C_COMPATIBILITY_HANDOFF_RESULT, freeze_dir, run_production_stage3
from offline.wall_build.states import Stage, StageStatus


class ProductionStage3ChainTests(unittest.TestCase):
    def test_needs_review_is_not_rewritten_as_pass(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="rv_s3_chain_"))
        dest = tmp / "run"
        freeze = freeze_dir(dest)
        freeze.mkdir(parents=True)
        (freeze / "descriptors.bin").write_bytes(b"RVS1")
        (freeze / "landmarks.json").write_text("{}\n", encoding="utf-8")
        (freeze / "freeze.json").write_text(
            json.dumps(
                {
                    "wallId": "wall_test",
                    "wallBuildRunId": "wb_run",
                    "colmapModelFingerprint": "abc",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        stages: dict = {}
        durations: dict = {}
        blocking: list[str] = []
        payload = {
            "gateResult": GATE3C_COMPATIBILITY_HANDOFF_RESULT,
            "stopBeforeSwift": True,
            "humanReviewRequired": True,
            "outputDirectory": str(freeze),
        }
        with patch("offline.wall_build.stage3_run.build_reference_matching", return_value=payload) as fn:
            result = run_production_stage3(
                wall_id="wall_test",
                root=tmp,
                run_id="wb_run",
                dest=dest,
                stage_statuses=stages,
                stage_durations=durations,
                blocking=blocking,
            )
        fn.assert_called_once()
        self.assertEqual(fn.call_args.kwargs.get("run_id"), "wb_run")
        self.assertEqual(result["gateResult"], "NEEDS REVIEW")
        self.assertNotEqual(stages[Stage.REFERENCE_MATCH.value]["status"], StageStatus.AUTO_PASS.value)
        self.assertEqual(stages[Stage.REFERENCE_MATCH.value]["status"], StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value)
        self.assertEqual(stages[Stage.REFERENCE_MATCH.value]["gateResult"], "NEEDS REVIEW")
        self.assertTrue(stages[Stage.REFERENCE_MAP.value]["freezeBound"])
        self.assertEqual(stages[Stage.REFERENCE_MAP.value]["status"], StageStatus.AUTO_PASS.value)

    def test_stop_does_not_continue(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="rv_s3_stop_"))
        dest = tmp / "run"
        dest.mkdir(parents=True)
        stages: dict = {}
        payload = {"gateResult": "STOP", "reasonCode": "STAGE3_SIM3_PROVENANCE_NOT_PROVEN", "errors": ["missing"]}
        with patch("offline.wall_build.stage3_run.build_reference_matching", return_value=payload) as fn:
            run_production_stage3(
                wall_id="wall_test",
                root=tmp,
                run_id="wb_run",
                dest=dest,
                stage_statuses=stages,
                stage_durations={},
                blocking=[],
            )
        fn.assert_called_once()
        self.assertEqual(fn.call_args.kwargs.get("run_id"), "wb_run")
        self.assertEqual(stages[Stage.REFERENCE_MATCH.value]["gateResult"], "STOP")
        self.assertEqual(stages[Stage.REFERENCE_MATCH.value]["status"], StageStatus.AUTO_FAIL.value)
        self.assertFalse(stages[Stage.REFERENCE_MAP.value]["freezeBound"])

    def test_legal_boundary_does_not_continue_after_stop(self) -> None:
        from offline.wall_build.stage3_run import run_stage3_legal_boundary

        tmp = Path(tempfile.mkdtemp(prefix="rv_s3_bound_"))
        dest = tmp / "run"
        dest.mkdir(parents=True)
        stages = {
            Stage.REFERENCE_MATCH.value: {
                "status": StageStatus.AUTO_FAIL.value,
                "gateResult": "STOP",
            }
        }
        extras = run_stage3_legal_boundary(
            wall_id="wall_test",
            root=tmp,
            run_id="wb_run",
            dest=dest,
            stage_statuses=stages,
            stage_durations={},
            three_c={"gateResult": "STOP", "errors": ["bind failed"]},
        )
        self.assertEqual(stages[Stage.PNP.value]["status"], StageStatus.BLOCKED.value)
        self.assertFalse(stages[Stage.PNP.value].get("invoked"))
        self.assertIsNone(extras["localizationPackage"])
        self.assertFalse(extras["fieldPnP"])


if __name__ == "__main__":
    unittest.main()
