"""Phase 1 gate-aware wall build orchestrator."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from offline.ingestion.pipeline import ingest, incoming_dir
from offline.ingestion.types import RunResult
from offline.qualification.pipeline import qualify

from .capability import downstream_stage_map
from .discovery import build_discovery, scan_wall_records
from .dxf_inventory import inventory_dxf_files
from .hard_bindings import HARD_BINDING_AUDIT
from .invocations import record
from .manifest import build_input_manifest, utc_now, verify_input_manifest
from .preflight import run_preflight
from .reports import write_reports
from .states import (
    PHASE1_EXECUTABLE_STAGES,
    AutomationReached,
    ReasonCode,
    RunTerminalStatus,
    Stage,
    StageStatus,
)
from .wall_id import wall_id_error

SCHEMA_VERSION = "wallBuild.report.1"
FORBIDDEN_COMMANDS = ("reconstruct", "register", "reference-match", "pnp")

_AUTOMATION_FOR_STAGE = {
    Stage.DISCOVERY: AutomationReached.DISCOVERY_COMPLETE,
    Stage.PREFLIGHT: AutomationReached.PREFLIGHT_COMPLETE,
    Stage.INGEST: AutomationReached.INGEST_COMPLETE,
    Stage.QUALIFY: AutomationReached.QUALIFICATION_COMPLETE,
}


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"wb_{stamp}_{secrets.token_hex(4)}"


def run_dir_for(root: Path, wall_id: str, run_id: str, *, rejected: bool) -> Path:
    base = root / "offline" / "work"
    if rejected:
        return base / "_phase1_rejected" / "wall_build" / run_id
    return base / wall_id / "wall_build" / run_id


def resolve_terminal_status(stage_statuses: dict[str, dict], freeze_ok: bool) -> RunTerminalStatus:
    """Pure mapping. Production Phase 1 never emits HUMAN_REVIEW_REQUIRED."""
    if not freeze_ok:
        return RunTerminalStatus.AUTO_FAIL
    ordered = list(stage_statuses.values())
    if any(item.get("status") == StageStatus.AUTO_FAIL.value for item in ordered):
        return RunTerminalStatus.AUTO_FAIL
    if any(item.get("status") == StageStatus.HUMAN_REVIEW_REQUIRED.value for item in ordered):
        return RunTerminalStatus.HUMAN_REVIEW_REQUIRED
    return RunTerminalStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED


def _stage(status: StageStatus, *, reason: ReasonCode | None = None, extra: dict | None = None) -> dict:
    payload = {"status": status.value, "invoked": False}
    if reason is not None:
        payload["reasonCode"] = reason.value
    if extra:
        payload.update(extra)
    return payload


def _map_ingest(summary) -> dict:
    warnings = list(summary.warnings or [])
    errors = list(summary.errors or [])
    extra = {
        "invoked": True,
        "ingestResult": summary.result.value,
        "warnings": warnings,
        "errors": errors,
        "imagesReadable": summary.images_readable,
    }
    if summary.result == RunResult.FAIL:
        reason = ReasonCode.INGEST_FAILED
        if any("changed" in err.lower() or "immutable" in err.lower() for err in errors):
            reason = ReasonCode.INPUT_MUTATED_DURING_RUN
        elif any("no readable photograph" in err.lower() for err in errors):
            reason = ReasonCode.MISSING_REQUIRED_SOURCE_IMAGES
        return _stage(StageStatus.AUTO_FAIL, reason=reason, extra=extra)
    # PASS and PASS WITH WARNINGS both AUTO_PASS (H1). Warnings stay warnings.
    extra["ingestWarningsPreserved"] = warnings
    return _stage(StageStatus.AUTO_PASS, extra=extra)


def _map_qualify(payload: dict) -> dict:
    extra = {
        "invoked": True,
        "qualifyResult": payload.get("result"),
        "incomingUnchanged": payload.get("incomingUnchanged"),
        "colmapReadiness": (payload.get("colmapReadiness") or {}).get("status"),
        "errors": list(payload.get("errors") or []),
    }
    if payload.get("incomingUnchanged") is False:
        return _stage(
            StageStatus.AUTO_FAIL,
            reason=ReasonCode.INPUT_MUTATED_DURING_RUN,
            extra=extra,
        )
    if payload.get("result") == "FAIL":
        return _stage(StageStatus.AUTO_FAIL, reason=ReasonCode.QUALIFY_FAILED, extra=extra)
    # colmapReadiness != READY must not become QUALIFY AUTO_FAIL.
    extra["colmapReadinessNotMappedToQualifyFailure"] = True
    return _stage(StageStatus.AUTO_PASS, extra=extra)


def _automation_reached(stage_statuses: dict[str, dict]) -> AutomationReached:
    reached = AutomationReached.NONE
    for stage in (Stage.DISCOVERY, Stage.PREFLIGHT, Stage.INGEST, Stage.QUALIFY):
        payload = stage_statuses.get(stage.value) or {}
        if payload.get("status") == StageStatus.AUTO_PASS.value:
            reached = _AUTOMATION_FOR_STAGE[stage]
        else:
            break
    return reached


def _next_stage(stage_statuses: dict[str, dict]) -> tuple[str, str, str | None]:
    for stage in (Stage.DISCOVERY, Stage.PREFLIGHT, Stage.INGEST, Stage.QUALIFY):
        payload = stage_statuses.get(stage.value) or {}
        status = payload.get("status")
        if status == StageStatus.AUTO_PASS.value:
            continue
        if status == StageStatus.SKIPPED.value:
            continue
        return stage.value, status, payload.get("reasonCode")
    recon = stage_statuses.get(Stage.RECONSTRUCTION.value) or {}
    return (
        Stage.RECONSTRUCTION.value,
        recon.get("status") or StageStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
        recon.get("reasonCode"),
    )


def run_wall_build(wall_id: str, root: Path, *, run_id: str | None = None) -> dict:
    started = perf_counter()
    run_start = utc_now()
    run_id = run_id or new_run_id()
    record("build")

    id_error = wall_id_error(wall_id)
    rejected = id_error is not None
    incoming = incoming_dir(root, wall_id) if not rejected else root / "incoming" / "_invalid"
    dest = run_dir_for(root, wall_id, run_id, rejected=rejected)
    dest.mkdir(parents=True, exist_ok=True)

    stage_durations: dict[str, float] = {}
    stage_statuses: dict[str, dict] = {}
    reason_codes: list[str] = []
    warnings: list[str] = []
    blocking: list[str] = []
    discovery: dict = {}
    preflight: dict = {}
    dxf_files: list[dict] = []
    manifest: dict = {
        "schemaVersion": "wallBuild.inputManifest.1",
        "runId": run_id,
        "wallId": wall_id,
        "runStartTime": run_start,
        "incomingRoot": str(incoming) if not rejected else None,
        "fileCount": 0,
        "files": [],
    }
    freeze_ok = True
    freeze_discrepancies: list[dict] = []

    def finish() -> dict:
        nonlocal freeze_ok, freeze_discrepancies
        if not rejected and incoming.is_dir() and manifest.get("files") is not None:
            freeze_ok, freeze_discrepancies = verify_input_manifest(incoming, manifest)
        if not freeze_ok:
            reason_codes.append(ReasonCode.INPUT_MUTATED_DURING_RUN.value)
            blocking.append("incoming files changed during the run")
            stage_statuses["INPUT_FREEZE"] = _stage(
                StageStatus.AUTO_FAIL,
                reason=ReasonCode.INPUT_MUTATED_DURING_RUN,
                extra={"discrepancies": freeze_discrepancies},
            )
        else:
            stage_statuses["INPUT_FREEZE"] = _stage(StageStatus.AUTO_PASS)

        for name, payload in list(stage_statuses.items()):
            code = payload.get("reasonCode")
            if code:
                reason_codes.append(code)
            for extra_code in payload.get("reasonCodes") or []:
                reason_codes.append(extra_code)

        unique_reasons = list(dict.fromkeys(reason_codes))
        terminal = resolve_terminal_status(stage_statuses, freeze_ok)
        reached = _automation_reached(stage_statuses)
        next_stage, next_status, next_reason = _next_stage(stage_statuses)
        run_end = utc_now()
        duration = round(perf_counter() - started, 4)

        classified = (discovery.get("classifiedInputs") or {}) if discovery else {}
        report = {
            "schemaVersion": SCHEMA_VERSION,
            "phase": "PHASE1_GATE_AWARE_ORCHESTRATOR",
            "runId": run_id,
            "wallId": wall_id,
            "runStartTime": run_start,
            "runEndTime": run_end,
            "runDurationSeconds": duration,
            "inputManifest": {
                "path": str(dest / "input_manifest.json"),
                "fileCount": manifest.get("fileCount"),
                "schemaVersion": manifest.get("schemaVersion"),
            },
            "discoveredFileCount": discovery.get("discoveredFileCount", 0),
            "classifiedInputs": classified,
            "ignoredUnknownFiles": discovery.get("ignoredUnknownFiles") or [],
            "captureCandidates": discovery.get("captureCandidates") or [],
            "mrkCandidates": discovery.get("mrkCandidates") or [],
            "metadataCandidates": discovery.get("metadataCandidates") or [],
            "modelCandidates": discovery.get("modelCandidates") or [],
            "dxfFiles": dxf_files,
            "ingestStatus": (stage_statuses.get(Stage.INGEST.value) or {}).get("status"),
            "qualifyStatus": (stage_statuses.get(Stage.QUALIFY.value) or {}).get("status"),
            "stageStatuses": stage_statuses,
            "reasonCodes": unique_reasons,
            "warnings": list(dict.fromkeys(warnings)),
            "automationReached": reached.value,
            "nextStage": next_stage,
            "nextStageStatus": next_status,
            "nextStageReason": next_reason,
            "blockingEvidence": blocking,
            "runTerminalStatus": terminal.value,
            "fieldTestReady": False,
            "fieldTestReadyLabel": "NO",
            "jinshidongUnattendedToFieldTestReady": "NO",
            "executableStageAllowlist": sorted(s.value for s in PHASE1_EXECUTABLE_STAGES),
            "forbiddenCommandsNotInvoked": list(FORBIDDEN_COMMANDS),
            "developmentGateScope": HARD_BINDING_AUDIT,
            "efficiency": {
                "runDurationSeconds": duration,
                "stageDurationsSeconds": stage_durations,
                "fileCount": discovery.get("discoveredFileCount", 0),
                "imageCount": discovery.get("imageCount", 0),
                "dxfCount": len(dxf_files),
                "captureCandidateCount": len(discovery.get("captureCandidates") or []),
                "mrkCandidateCount": len(discovery.get("mrkCandidates") or []),
                "metadataCandidateCount": len(discovery.get("metadataCandidates") or []),
                "modelCandidateCount": len(discovery.get("modelCandidates") or []),
                "warningCount": len(list(dict.fromkeys(warnings))),
                "autoFailure": terminal == RunTerminalStatus.AUTO_FAIL,
                "reviewStop": terminal == RunTerminalStatus.HUMAN_REVIEW_REQUIRED,
                "automationReached": reached.value,
                "fieldAcquisitionDuration": None,
                "flightCount": None,
                "routeAuthoringDuration": None,
                "routeCount": None,
                "supplementalCapture": None,
                "manualIntervention": None,
                "fieldNotes": None,
            },
            "runOutputDir": str(dest),
        }
        (dest / "input_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        write_reports(dest, report)
        (dest / "run.log").write_text(
            "\n".join(
                [
                    f"runId={run_id}",
                    f"wallId={wall_id}",
                    f"terminal={terminal.value}",
                    f"automationReached={reached.value}",
                    *[f"duration.{name}={value}" for name, value in stage_durations.items()],
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return report

    if rejected:
        stage_statuses[Stage.DISCOVERY.value] = _stage(
            StageStatus.AUTO_FAIL, reason=id_error
        )
        blocking.append(f"wall_id rejected: {id_error.value}")
        reason_codes.append(id_error.value)
        return finish()

    t0 = perf_counter()
    if incoming.is_dir():
        manifest = build_input_manifest(
            run_id=run_id,
            wall_id=wall_id,
            incoming=incoming,
            run_start_time=run_start,
        )
    records = scan_wall_records(incoming) if incoming.is_dir() else []
    discovery = build_discovery(wall_id, incoming, records)
    dxf_files = inventory_dxf_files(wall_id, incoming, discovery.get("dxfFiles") or [])
    discovery["dxfParseResults"] = dxf_files
    discovery["dxfFiles"] = dxf_files
    if incoming.is_dir():
        stage_statuses[Stage.DISCOVERY.value] = _stage(
            StageStatus.AUTO_PASS,
            extra={"invoked": True, "discoveredFileCount": discovery["discoveredFileCount"]},
        )
        record("discovery")
    else:
        reason = (
            ReasonCode.WALL_PATH_NOT_DIRECTORY
            if incoming.exists()
            else ReasonCode.MISSING_WALL_DIRECTORY
        )
        stage_statuses[Stage.DISCOVERY.value] = _stage(StageStatus.AUTO_FAIL, reason=reason)
        blocking.append(reason.value)
    stage_durations[Stage.DISCOVERY.value] = round(perf_counter() - t0, 4)
    warnings.extend(discovery.get("inventoryWarnings") or [])

    if stage_statuses[Stage.DISCOVERY.value]["status"] != StageStatus.AUTO_PASS.value:
        _block_remaining(stage_statuses, from_stage=Stage.PREFLIGHT)
        return finish()

    t0 = perf_counter()
    record("preflight")
    preflight = run_preflight(
        wall_id=wall_id,
        incoming=incoming,
        records=records,
        discovery=discovery,
    )
    stage_durations[Stage.PREFLIGHT.value] = round(perf_counter() - t0, 4)
    warnings.extend(preflight.get("warnings") or [])
    reason_codes.extend(preflight.get("reasonCodes") or [])
    extra = {"invoked": True, "checks": preflight.get("checks") or {}}
    if preflight["status"] == StageStatus.AUTO_FAIL.value:
        reason = ReasonCode(preflight["reasonCodes"][0]) if preflight.get("reasonCodes") else ReasonCode.INGEST_FAILED
        stage_statuses[Stage.PREFLIGHT.value] = _stage(
            StageStatus.AUTO_FAIL, reason=reason, extra=extra
        )
        blocking.extend(preflight.get("errors") or [])
        _block_remaining(stage_statuses, from_stage=Stage.INGEST)
        return finish()
    stage_statuses[Stage.PREFLIGHT.value] = _stage(StageStatus.AUTO_PASS, extra=extra)

    t0 = perf_counter()
    record("ingest")
    summary = ingest(wall_id, root)
    stage_durations[Stage.INGEST.value] = round(perf_counter() - t0, 4)
    mapped = _map_ingest(summary)
    stage_statuses[Stage.INGEST.value] = mapped
    warnings.extend(mapped.get("warnings") or [])
    if mapped["status"] != StageStatus.AUTO_PASS.value:
        blocking.extend(mapped.get("errors") or ["ingest failed"])
        _block_remaining(stage_statuses, from_stage=Stage.QUALIFY)
        return finish()

    t0 = perf_counter()
    record("qualify")
    qualify_payload = qualify(wall_id, root)
    stage_durations[Stage.QUALIFY.value] = round(perf_counter() - t0, 4)
    mapped_q = _map_qualify(qualify_payload)
    stage_statuses[Stage.QUALIFY.value] = mapped_q
    if mapped_q["status"] != StageStatus.AUTO_PASS.value:
        blocking.extend(mapped_q.get("errors") or ["qualify failed"])
        _block_remaining(stage_statuses, from_stage=Stage.RECONSTRUCTION)
        return finish()

    stage_statuses.update(downstream_stage_map())
    recon = stage_statuses[Stage.RECONSTRUCTION.value]
    blocking.append(
        recon.get("reasonCode")
        or ReasonCode.GENERIC_STAGE2_NOT_APPROVED.value
    )
    return finish()


def _block_remaining(stage_statuses: dict[str, dict], *, from_stage: Stage) -> None:
    sequence = [
        Stage.PREFLIGHT,
        Stage.INGEST,
        Stage.QUALIFY,
        Stage.RECONSTRUCTION,
        Stage.METRIC_REGISTRATION,
        Stage.REGISTER,
        Stage.REFERENCE_MATCH,
        Stage.PNP,
        Stage.REFERENCE_MAP,
        Stage.ROUTE_COORDINATE_REGISTRATION,
        Stage.ROUTE_PACKAGE_BUILD,
    ]
    started = False
    downstream = downstream_stage_map()
    for stage in sequence:
        if stage == from_stage:
            started = True
        if not started:
            continue
        if stage.value in stage_statuses:
            continue
        extra = {
            "executionAllowed": False,
            "executionDeniedReason": ReasonCode.PHASE1_STAGE_NOT_IN_ALLOWLIST.value,
            "invoked": False,
        }
        if stage in PHASE1_EXECUTABLE_STAGES:
            stage_statuses[stage.value] = _stage(
                StageStatus.BLOCKED,
                reason=ReasonCode.UPSTREAM_STAGE_NOT_COMPLETE,
                extra=extra,
            )
        else:
            # Upstream allowlisted stages did not AUTO_PASS, so later
            # stages are BLOCKED. Reconstruction is still not invoked.
            payload = downstream[stage.value]
            payload = {
                **payload,
                "status": StageStatus.BLOCKED.value,
                "reasonCode": ReasonCode.UPSTREAM_STAGE_NOT_COMPLETE.value,
                **extra,
            }
            stage_statuses[stage.value] = payload
