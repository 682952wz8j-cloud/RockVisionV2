from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.verify import DEFAULT_UNITTEST_MODULES, VERIFY_IS_NOT_A_GATE_PASS, run_verify


class EngineeringWorkflowV2Tests(unittest.TestCase):
    def test_workflow_doc_defines_risk_levels_and_rules(self) -> None:
        text = (ROOT / "docs" / "ENGINEERING_WORKFLOW_V2.md").read_text(encoding="utf-8")
        for token in (
            "R0 — Mechanical",
            "R1 — Local Code",
            "R2 — Pipeline",
            "R3 — Gate-Critical",
            "Cursor may create local checkpoint commits",
            "must not push unless explicitly authorized",
            "must not independently declare a Gate PASS",
            "Risk classification never overrides",
            "must not be converted into a Gate",
            "./rockvision verify",
        ):
            self.assertIn(token, text)

    def test_verify_is_not_a_gate_pass(self) -> None:
        self.assertTrue(VERIFY_IS_NOT_A_GATE_PASS)
        cli = (ROOT / "tools" / "rockvision.py").read_text(encoding="utf-8")
        self.assertIn('sub.add_parser(\n        "verify"', cli)
        self.assertIn("Not a Gate PASS", cli)
        wrapper = (ROOT / "offline" / "verify.py").read_text(encoding="utf-8")
        self.assertIn("not a Gate PASS", wrapper)

    def test_verify_aggregates_existing_unittest_modules(self) -> None:
        expected = {
            "offline.tests.test_ingestion",
            "offline.tests.test_qualification",
            "offline.tests.test_ply_stats",
            "offline.tests.test_colmap",
            "offline.tests.test_metric_registration",
            "offline.tests.test_height_enforcement",
            "offline.tests.test_positioning_quality",
            "offline.tests.test_colmap_source_identity",
            "offline.tests.test_stage2_selection",
            "offline.tests.test_stage2_terra",
            "offline.tests.test_terra_ply_product",
            "offline.tests.test_stage2_rule_c",
            "offline.tests.test_stage2_regression",
            "offline.tests.test_wall_build_phase1",
            "offline.tests.test_wall_build_stage2",
            "offline.tests.test_reference_matching",
            "offline.tests.test_pnp",
            "offline.tests.test_localization_package",
            "offline.tests.test_stage3_run_binding",
            "offline.tests.test_localization_package_e2e",
            "offline.tests.test_engineering_workflow",
        }
        self.assertEqual(set(DEFAULT_UNITTEST_MODULES), expected)

    def test_verify_wrapper_runs_this_module_only(self) -> None:
        code = run_verify(["offline.tests.test_engineering_workflow.EngineeringWorkflowV2Tests.test_verify_is_not_a_gate_pass"])
        self.assertEqual(code, 0)
