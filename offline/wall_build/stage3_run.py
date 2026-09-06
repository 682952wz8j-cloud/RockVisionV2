"""Production Stage 3 on the current wall_build runId.

Always calls reference-match with an explicit --run-id. Never selects latest.
Never falls back to the legacy work tree. Does not publish.
"""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from .invocations import record
from .states import ReasonCode, Stage, StageStatus

FREEZE_FILES = ("descriptors.bin", "landmarks.json", "freeze.json")
ASSOCIATION_RADIUS_NAME = "baseline_2px"
GATE3C_COMPATIBILITY_HANDOFF_RESULT = "NEEDS REVIEW"


def _stage(status: StageStatus, *, reason: ReasonCode | str | None = None, extra: dict | None = None) -> dict:
    payload = {"status": status.value, "invoked": False}
    if reason is not None:
        payload["reasonCode"] = reason.value if isinstance(reason, ReasonCode) else str(reason)
    if extra:
        payload.update(extra)
    return payload


def freeze_dir(run_dir: Path) -> Path:
    return run_dir / "reference_matching" / ASSOCIATION_RADIUS_NAME


def build_reference_matching(wall_id: str, root: Path, *, run_id: str | None = None) -> dict:
    """Lazy import so wall_build can load without importing the 3C pipeline."""
    from offline.reference_matching.pipeline import build_reference_matching as impl

    return impl(wall_id, root, run_id=run_id)


def freeze_bound(run_dir: Path, *, wall_id: str, run_id: str) -> bool:
    dest = freeze_dir(run_dir)
    if not all((dest / name).is_file() for name in FREEZE_FILES):
        return False
    try:
        freeze = json.loads((dest / "freeze.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(freeze, dict):
        return False
    return (
        freeze.get("wallId") == wall_id
        and freeze.get("wallBuildRunId") == run_id
        and isinstance(freeze.get("colmapModelFingerprint"), str)
        and bool(freeze.get("colmapModelFingerprint"))
    )


def metric_registration_passed(stage_statuses: dict[str, dict]) -> bool:
    recon = stage_statuses.get(Stage.RECONSTRUCTION.value) or {}
    metric = stage_statuses.get(Stage.METRIC_REGISTRATION.value) or {}
    return (
        recon.get("status") == StageStatus.AUTO_PASS.value
        and recon.get("gateResult") == "PASS"
        and metric.get("status") == StageStatus.AUTO_PASS.value
        and metric.get("validationStatus") == "VALIDATED"
        and metric.get("sWallColmapWritten") is True
        and metric.get("gateResult") == "PASS"
    )


def run_production_stage3(
    *,
    wall_id: str,
    root: Path,
    run_id: str,
    dest: Path,
    stage_statuses: dict[str, dict],
    stage_durations: dict[str, float],
    blocking: list[str],
) -> dict:
    """Bind and run production 3C on this run. run_id is required."""
    if not run_id:
        raise ValueError("production Stage 3 requires run_id")

    t0 = perf_counter()
    record("reference-match")
    # Same production path as ./rockvision reference-match <wall_id> --run-id <runId>.
    payload = build_reference_matching(wall_id, root, run_id=run_id)
    gate = str(payload.get("gateResult") or "STOP")
    freeze_ok = freeze_bound(dest, wall_id=wall_id, run_id=run_id)
    freeze_path = str(freeze_dir(dest)) if freeze_ok else None
    stage_durations[Stage.REFERENCE_MATCH.value] = round(perf_counter() - t0, 4)

    map_status = StageStatus.AUTO_PASS if freeze_ok else StageStatus.AUTO_FAIL
    match_status = StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED
    match_reason: ReasonCode | str | None = None
    if gate == "STOP" or payload.get("errors"):
        match_status = StageStatus.AUTO_FAIL
        match_reason = str(payload.get("reasonCode") or "STAGE3_STOP")
        blocking.append(match_reason)
        if not freeze_ok:
            map_status = StageStatus.AUTO_FAIL
    elif gate == GATE3C_COMPATIBILITY_HANDOFF_RESULT:
        # Swift handoff label. Not Stage 3 PASS. Do not rewrite as PASS.
        match_status = StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED
        match_reason = "GATE3C_COMPATIBILITY_HANDOFF"
        if not freeze_ok:
            map_status = StageStatus.AUTO_FAIL
            blocking.append("STAGE3_FREEZE_BIND_FAILED")
    else:
        match_status = StageStatus.AUTO_FAIL
        match_reason = str(payload.get("reasonCode") or gate)
        blocking.append(str(match_reason))

    stage_statuses[Stage.REFERENCE_MAP.value] = _stage(
        map_status,
        reason=None if map_status == StageStatus.AUTO_PASS else str(payload.get("reasonCode") or "STAGE3_FREEZE_BIND_FAILED"),
        extra={
            "invoked": True,
            "executionAllowed": True,
            "freezeBound": freeze_ok,
            "freezeDirectory": freeze_path,
            "descriptors": str(freeze_dir(dest) / "descriptors.bin") if freeze_ok else None,
            "landmarks": str(freeze_dir(dest) / "landmarks.json") if freeze_ok else None,
            "wallBuildRunId": run_id if freeze_ok else None,
        },
    )
    stage_statuses[Stage.REFERENCE_MATCH.value] = _stage(
        match_status,
        reason=match_reason,
        extra={
            "invoked": True,
            "executionAllowed": True,
            "productionBound": True,
            "legacyFallback": False,
            "runId": run_id,
            "gateResult": gate,
            "stopBeforeSwift": bool(payload.get("stopBeforeSwift")),
            "humanReviewRequired": bool(payload.get("humanReviewRequired")),
            "outputDirectory": payload.get("outputDirectory") or str(freeze_dir(dest)),
            "reasonCodeFromBind": payload.get("reasonCode"),
        },
    )
    return payload


def run_stage3_legal_boundary(
    *,
    wall_id: str,
    root: Path,
    run_id: str,
    dest: Path,
    stage_statuses: dict[str, dict],
    stage_durations: dict[str, float],
    three_c: dict,
) -> dict:
    """Local package validate + pinned OpenCV PnP self-test. No field session, no publish."""
    extras: dict = {
        "localizationPackage": None,
        "pnpSelfTest": None,
        "fieldPnP": False,
        "fieldTestReady": False,
    }
    gate = str(three_c.get("gateResult") or "STOP")
    freeze_ok = freeze_bound(dest, wall_id=wall_id, run_id=run_id)
    match = stage_statuses.get(Stage.REFERENCE_MATCH.value) or {}
    if gate == "STOP" or not freeze_ok or match.get("status") == StageStatus.AUTO_FAIL.value:
        stage_statuses[Stage.PNP.value] = _stage(
            StageStatus.BLOCKED,
            reason=ReasonCode.UPSTREAM_STAGE_NOT_COMPLETE,
            extra={"invoked": False, "executionAllowed": False, "fieldPnP": False},
        )
        return extras

    t0 = perf_counter()
    try:
        from offline.localization_package.from_run import construct_and_validate_from_run

        extras["localizationPackage"] = construct_and_validate_from_run(
            wall_id=wall_id,
            root=root,
            run_id=run_id,
            run_dir=dest,
            freeze_dir=freeze_dir(dest),
        )
    except Exception as exc:
        extras["localizationPackage"] = {
            "constructed": False,
            "packageState": "NOT_PACKAGE_READY",
            "error": str(exc),
            "published": False,
        }
    stage_durations["LOCALIZATION_PACKAGE"] = round(perf_counter() - t0, 4)

    t0 = perf_counter()
    record("pnp-self-test")
    try:
        from offline.pnp.opencv_cli import run_self_test

        self_test = run_self_test(root)
        pnp_ok = bool(self_test.get("pass"))
        extras["pnpSelfTest"] = {
            "pass": pnp_ok,
            "cvVersion": self_test.get("cvVersion"),
            "fieldSession": False,
        }
        stage_statuses[Stage.PNP.value] = _stage(
            StageStatus.AUTO_PASS if pnp_ok else StageStatus.AUTO_FAIL,
            reason=None if pnp_ok else "PNP_SELF_TEST_FAILED",
            extra={
                "invoked": True,
                "executionAllowed": True,
                "kind": "pinned_opencv_self_test",
                "fieldPnP": False,
                "gate3D": False,
                "gate3E": False,
                "gate4": False,
                "cvVersion": self_test.get("cvVersion"),
            },
        )
    except Exception as exc:
        extras["pnpSelfTest"] = {"pass": False, "error": str(exc), "fieldSession": False}
        stage_statuses[Stage.PNP.value] = _stage(
            StageStatus.AUTO_FAIL,
            reason="PNP_SELF_TEST_FAILED",
            extra={
                "invoked": True,
                "executionAllowed": True,
                "kind": "pinned_opencv_self_test",
                "fieldPnP": False,
                "error": str(exc),
            },
        )
    stage_durations[Stage.PNP.value] = round(perf_counter() - t0, 4)
    return extras

