"""Global Generic Stage 2 capability state.

These fields are production capability, not a per-wall run result.
A wall may still fail data/evidence gates while capability remains PASS.
"""

from __future__ import annotations

GENERIC_STAGE2_PASS = True
GENERIC_STAGE2_PASS_ENABLED = True
PRODUCTION_BUILD_STAGE2_ENABLED = True
GENERIC_STAGE2_CAPABILITY_STATUS = "PASS"
REMAINING_GENERIC_STAGE2_CORRECTNESS_BLOCKERS = 0


def capability_fields() -> dict:
    return {
        "genericStage2Pass": GENERIC_STAGE2_PASS,
        "genericStage2Capability": GENERIC_STAGE2_CAPABILITY_STATUS,
        "productionBuildStage2Enabled": PRODUCTION_BUILD_STAGE2_ENABLED,
    }
