"""Capability / Gate checks for stages production build must not execute.

Generic Stage 2 reconstruction and metric registration are executable.
Stage 3 / route capabilities remain locked.
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


def downstream_stage_map() -> dict[str, dict]:
    not_allowlisted = blocked(
        ReasonCode.PHASE1_STAGE_NOT_IN_ALLOWLIST,
        detail="Stage 3 / legacy register is not on the production executable allowlist.",
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
        Stage.REGISTER.value: not_allowlisted,
        Stage.REFERENCE_MATCH.value: dict(not_allowlisted),
        Stage.PNP.value: dict(not_allowlisted),
        Stage.REFERENCE_MAP.value: dict(not_allowlisted),
        Stage.ROUTE_COORDINATE_REGISTRATION.value: route_blocked,
        Stage.ROUTE_PACKAGE_BUILD.value: package_blocked,
    }
