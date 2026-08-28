"""Capability / Gate checks for stages Phase 1 must not execute.

Same facts for every wall_id. Reconstruction is never invoked.
"""

from __future__ import annotations

from .states import ReasonCode, Stage, StageStatus


def blocked(reason: ReasonCode, *, detail: str | None = None) -> dict:
    payload = {
        "status": StageStatus.BLOCKED.value,
        "executionAllowed": False,
        "executionDeniedReason": ReasonCode.PHASE1_STAGE_NOT_IN_ALLOWLIST.value,
        "reasonCode": reason.value,
        "invoked": False,
    }
    if detail:
        payload["detail"] = detail
    return payload


def reconstruction_check() -> dict:
    """Never invoke reconstruct. Allowlist denial and capability gap are both recorded."""
    return {
        "status": StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
        "capabilityStatus": StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
        "executionAllowed": False,
        "executionDeniedReason": ReasonCode.PHASE1_STAGE_NOT_IN_ALLOWLIST.value,
        "reasonCode": ReasonCode.GENERIC_STAGE2_NOT_APPROVED.value,
        "reasonCodes": [
            ReasonCode.PHASE1_STAGE_NOT_IN_ALLOWLIST.value,
            ReasonCode.GENERIC_STAGE2_NOT_APPROVED.value,
        ],
        "invoked": False,
    }


def downstream_stage_map() -> dict[str, dict]:
    recon = reconstruction_check()
    blocked_by_recon = blocked(
        ReasonCode.UPSTREAM_STAGE_NOT_COMPLETE,
        detail="Upstream RECONSTRUCTION did not AUTO_PASS.",
    )
    route_blocked = blocked(
        ReasonCode.DXF_COORDINATE_PROVENANCE_METHOD_NOT_APPROVED,
        detail="Generic DXF → WallMetricMeters method is not approved.",
    )
    package_blocked = blocked(
        ReasonCode.ROUTE_PACKAGE_NOT_AUTHORIZED,
        detail="Production route package / routes.json is not authorized.",
    )
    return {
        Stage.RECONSTRUCTION.value: recon,
        Stage.METRIC_REGISTRATION.value: blocked_by_recon,
        Stage.REGISTER.value: blocked_by_recon,
        Stage.REFERENCE_MATCH.value: blocked_by_recon,
        Stage.PNP.value: blocked_by_recon,
        Stage.REFERENCE_MAP.value: blocked_by_recon,
        Stage.ROUTE_COORDINATE_REGISTRATION.value: route_blocked,
        Stage.ROUTE_PACKAGE_BUILD.value: package_blocked,
    }
