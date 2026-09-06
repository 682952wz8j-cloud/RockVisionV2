"""Capability / Gate checks for stages production build must not execute.

Generic Stage 2 plus this-run Stage 3 freeze / 3C / pinned PnP self-test
are executable. Legacy register and route/package capabilities remain locked.
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
        detail="Legacy register is not on the production executable allowlist.",
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
        Stage.ROUTE_COORDINATE_REGISTRATION.value: route_blocked,
        Stage.ROUTE_PACKAGE_BUILD.value: package_blocked,
    }
