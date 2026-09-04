"""Approved Generic Stage 2 production sequence for wall-build.

Uses one select_stage2_inputs result and the same sources object for
height, positioning quality, reconstruction, and metric registration.
Does not call the legacy reconstruct/register path (sources=None).
"""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from offline.colmap.pipeline import reconstruct
from offline.metric_registration.height_datum import evaluate_generic_height_from_sources
from offline.metric_registration.pipeline import register
from offline.metric_registration.positioning_quality import evaluate_positioning_quality_from_sources
from offline.stage2_capability import capability_fields
from offline.stage2_selection.artifact import write_selection_artifact
from offline.stage2_selection.select import select_stage2_inputs
from offline.stage2_selection.sources import sources_from_selection

from .invocations import record
from .states import ReasonCode, Stage, StageStatus

_STATUS_BY_TOKEN = {
    "AUTO_PASS": StageStatus.AUTO_PASS,
    "PASS": StageStatus.AUTO_PASS,
    "AUTO_FAIL": StageStatus.AUTO_FAIL,
    "FAIL": StageStatus.AUTO_FAIL,
    "HUMAN_REVIEW_REQUIRED": StageStatus.HUMAN_REVIEW_REQUIRED,
    "DEVELOPMENT_GATE_REVIEW_REQUIRED": StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED,
    "NEEDS REVIEW": StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED,
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _stage_status(token: str | None, *, fallback: StageStatus = StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED) -> StageStatus:
    if not token:
        return fallback
    return _STATUS_BY_TOKEN.get(str(token), fallback)


def _stage(
    status: StageStatus,
    *,
    reason: ReasonCode | str | None = None,
    extra: dict | None = None,
) -> dict:
    payload = {"status": status.value, "invoked": False, **capability_fields()}
    if reason is not None:
        payload["reasonCode"] = reason.value if isinstance(reason, ReasonCode) else str(reason)
    if extra:
        payload.update(extra)
    return payload


def run_production_stage2(
    *,
    wall_id: str,
    root: Path,
    incoming: Path,
    dest: Path,
    stage_statuses: dict[str, dict],
    stage_durations: dict[str, float],
    blocking: list[str],
    frozen_terra_ply_product: dict | None = None,
) -> None:
    """Execute approved Generic Stage 2. Stops fail-closed before COLMAP when possible."""
    t0 = perf_counter()
    record("stage2-selection")
    selection = select_stage2_inputs(
        wall_id, root, run_id=dest.name, frozen_terra_ply_product=frozen_terra_ply_product
    )
    write_selection_artifact(dest / "stage2_input_selection.json", selection)
    sources = sources_from_selection(selection)
    selection_status = str(selection.get("selectionStatus") or StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value)
    mapped = _stage_status(selection_status)
    stage_statuses[Stage.STAGE2_SELECTION.value] = _stage(
        mapped,
        reason=None if mapped == StageStatus.AUTO_PASS else ReasonCode.STAGE2_SELECTION_NOT_AUTO_PASS,
        extra={
            "invoked": True,
            "executionAllowed": True,
            "selectionStatus": selection_status,
            "selectedImageCount": len((selection.get("selectedCapture") or {}).get("memberRelativePaths") or ()),
            "sourcesBound": sources is not None,
        },
    )
    stage_durations[Stage.STAGE2_SELECTION.value] = round(perf_counter() - t0, 4)
    if sources is None or mapped != StageStatus.AUTO_PASS:
        blocking.append(selection_status)
        return

    t0 = perf_counter()
    record("height-datum")
    height = evaluate_generic_height_from_sources(incoming, sources)
    _write_json(dest / "height_vertical_datum.json", height)
    height_ok = bool(height.get("heightGateExecutionAllowed"))
    height_status = _stage_status(height.get("heightVerticalDatumProvenance"))
    if not height_ok and height_status == StageStatus.AUTO_PASS:
        height_status = StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED
    stage_statuses[Stage.HEIGHT_VERTICAL_DATUM.value] = _stage(
        height_status if not height_ok else StageStatus.AUTO_PASS,
        reason=None if height_ok else str(height.get("reasonCode") or "HEIGHT_NOT_PROVEN"),
        extra={
            "invoked": True,
            "executionAllowed": True,
            "heightGateExecutionAllowed": height_ok,
            "heightVerticalDatumProvenance": height.get("heightVerticalDatumProvenance"),
        },
    )
    stage_durations[Stage.HEIGHT_VERTICAL_DATUM.value] = round(perf_counter() - t0, 4)
    if not height_ok:
        blocking.append(str(height.get("reasonCode") or height.get("heightVerticalDatumProvenance")))
        return

    t0 = perf_counter()
    record("positioning-quality")
    positioning = evaluate_positioning_quality_from_sources(incoming, sources)
    _write_json(dest / "positioning_quality.json", positioning)
    pq_ok = bool(positioning.get("positioningQualityExecutionAllowed"))
    pq_status = _stage_status(positioning.get("positioningQualityProvenance"))
    if not pq_ok and pq_status == StageStatus.AUTO_PASS:
        pq_status = StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED
    stage_statuses[Stage.POSITIONING_QUALITY.value] = _stage(
        pq_status if not pq_ok else StageStatus.AUTO_PASS,
        reason=None if pq_ok else str(positioning.get("positioningQualityReasonCode") or "POSITIONING_QUALITY_NOT_PROVEN"),
        extra={
            "invoked": True,
            "executionAllowed": True,
            "positioningQualityExecutionAllowed": pq_ok,
            "positioningQualityProvenance": positioning.get("positioningQualityProvenance"),
            "selectedFrameCount": positioning.get("selectedFrameCount"),
            "fixedFrameCount": positioning.get("fixedFrameCount"),
            "nonFixedFrameCount": positioning.get("nonFixedFrameCount"),
            "missingOrUnparseableFrameCount": positioning.get("missingOrUnparseableFrameCount"),
        },
    )
    stage_durations[Stage.POSITIONING_QUALITY.value] = round(perf_counter() - t0, 4)
    if not pq_ok:
        blocking.append(str(positioning.get("positioningQualityReasonCode") or positioning.get("positioningQualityProvenance")))
        return

    t0 = perf_counter()
    record("reconstruct")
    colmap_dir = dest / "colmap"
    recon = reconstruct(wall_id, root, sources=sources, dest=colmap_dir)
    recon_gate = str(recon.get("gateResult") or "FAIL")
    recon_ok = recon_gate == "PASS"
    recon_status = _stage_status(recon_gate, fallback=StageStatus.AUTO_FAIL)
    stage_statuses[Stage.RECONSTRUCTION.value] = _stage(
        StageStatus.AUTO_PASS if recon_ok else recon_status,
        reason=None if recon_ok else ReasonCode.RECONSTRUCTION_FAILED,
        extra={
            "invoked": True,
            "executionAllowed": True,
            "gateResult": recon_gate,
            "sourceImages": recon.get("sourceImages"),
            "registeredImages": recon.get("registeredImages"),
            "selectedModelRelativePath": recon.get("selectedModelRelativePath"),
            "colmapDir": str(colmap_dir),
            "legacyPathUsed": False,
        },
    )
    stage_durations[Stage.RECONSTRUCTION.value] = round(perf_counter() - t0, 4)
    if not recon_ok:
        blocking.append(recon_gate)
        return

    t0 = perf_counter()
    record("register")
    metric_dir = dest / "metric_registration"
    payload = register(
        wall_id,
        root,
        sources=sources,
        dest=metric_dir,
        colmap_dir=colmap_dir,
        run_id=dest.name,
    )
    validated = payload.get("validationStatus") == "VALIDATED" and "scale" in payload
    gate = str(payload.get("gateResult") or "FAIL")
    metric_ok = validated and gate == "PASS"
    metric_status = StageStatus.AUTO_PASS if metric_ok else _stage_status(gate, fallback=StageStatus.AUTO_FAIL)
    identity_reason = payload.get("colmapSourceIdentityReasonCode")
    reason = None
    if not metric_ok:
        reason = payload.get("reasonCode") or identity_reason or ReasonCode.METRIC_REGISTRATION_FAILED.value
    stage_statuses[Stage.METRIC_REGISTRATION.value] = _stage(
        metric_status,
        reason=reason,
        extra={
            "invoked": True,
            "executionAllowed": True,
            "gateResult": gate,
            "validationStatus": payload.get("validationStatus"),
            "correspondenceCount": payload.get("correspondenceCount"),
            "scale": payload.get("scale"),
            "holdoutMetrics": payload.get("holdoutMetrics"),
            "outputFrame": payload.get("outputFrame") or "WallLocal",
            "wallMetricMetersProvenance": payload.get("wallMetricMetersProvenance") or "NOT_CLAIMED",
            "colmapSourceIdentityReasonCode": identity_reason,
            "colmapSourceIdentityExecutionAllowed": payload.get("colmapSourceIdentityExecutionAllowed"),
            "legacyPathUsed": False,
            "sWallColmapWritten": (metric_dir / "S_wall_colmap.json").is_file(),
        },
    )
    stage_durations[Stage.METRIC_REGISTRATION.value] = round(perf_counter() - t0, 4)
    if not metric_ok:
        blocking.append(str(reason or gate))
