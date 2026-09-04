"""Thin aggregator for existing deterministic unit tests.

This is not a Gate PASS, FREEZE, or Stage advance.
It does not change production algorithm behavior.
"""

from __future__ import annotations

import unittest
from typing import Sequence

VERIFY_IS_NOT_A_GATE_PASS = True

DEFAULT_UNITTEST_MODULES: tuple[str, ...] = (
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
    "offline.tests.test_publisher",
    "offline.tests.test_engineering_workflow",
)


def run_verify(modules: Sequence[str] | None = None) -> int:
    names = list(modules or DEFAULT_UNITTEST_MODULES)
    print("RockVision verify — automated deterministic checks")
    print("This is NOT a Gate PASS, FREEZE, or Stage advance.")
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1
