"""Bind production Stage 3 to one explicit validated wall_build/<runId>.

Does not select latest. Does not fall back to the legacy work tree.
Does not infer identity from directory names, timestamps, or filenames.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from offline.colmap.source_identity import (
    PROVENANCE_ORIGIN_RECONSTRUCTION_RUN,
    SELECTED_MODEL_RELATIVE_PATH,
    load_provenance,
    model_fingerprint,
    resolve_recorded_model_dir,
)
from offline.metric_registration.serialize import load_sim3
from offline.wall_build.states import Stage, StageStatus

REQUIRED_AUTO_PASS_STAGES = (
    "INPUT_FREEZE",
    Stage.STAGE2_SELECTION.value,
    Stage.HEIGHT_VERTICAL_DATUM.value,
    Stage.POSITIONING_QUALITY.value,
    Stage.RECONSTRUCTION.value,
    Stage.METRIC_REGISTRATION.value,
)

REASON_RUN_NOT_FOUND = "STAGE3_WALL_BUILD_RUN_NOT_FOUND"
REASON_RUN_ID_MISMATCH = "STAGE3_WALL_BUILD_RUN_MISMATCH"
REASON_WALL_ID_MISMATCH = "STAGE3_WALL_ID_MISMATCH"
REASON_GATES_NOT_PASS = "STAGE3_STAGE2_GATES_NOT_PASS"
REASON_IDENTITY_NOT_PROVEN = "STAGE3_COLMAP_IDENTITY_NOT_PROVEN"
REASON_FINGERPRINT_MISMATCH = "STAGE3_MODEL_FINGERPRINT_MISMATCH"
REASON_SIM3_NOT_VALIDATED = "STAGE3_SIM3_NOT_VALIDATED"
REASON_SIM3_PROVENANCE_NOT_PROVEN = "STAGE3_SIM3_PROVENANCE_NOT_PROVEN"
REASON_LEGACY_FORBIDDEN = "STAGE3_LEGACY_FALLBACK_FORBIDDEN"
REASON_UNSAFE_RUN_ID = "STAGE3_UNSAFE_RUN_ID"


class ProductionStage3BindError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProductionStage3Inputs:
    wall_id: str
    run_id: str
    run_dir: Path
    colmap_dir: Path
    model_dir: Path
    sim3_path: Path
    model_fingerprint: str
    identity: dict
    report: dict
    sim3: dict


def wall_build_run_dir(root: Path, wall_id: str, run_id: str) -> Path:
    return root / "offline" / "work" / wall_id / "wall_build" / run_id


def legacy_stage3_paths(root: Path, wall_id: str) -> tuple[Path, Path]:
    """Development-only locations. Production --run-id must not use these."""
    work = root / "offline" / "work" / wall_id
    return work / "colmap" / "sparse" / "0", work / "metric_registration" / "S_wall_colmap.json"


def _safe_run_id(run_id: str) -> bool:
    if not isinstance(run_id, str) or not run_id:
        return False
    if any(token in run_id for token in ("..", "/", "\\", ":", "@")):
        return False
    return run_id[0].isalnum() and all(ch.isalnum() or ch in "-_" for ch in run_id)


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _stage_ok(report: dict, name: str) -> bool:
    stages = report.get("stageStatuses") or {}
    item = stages.get(name) or {}
    if not isinstance(item, dict):
        return False
    return item.get("status") == StageStatus.AUTO_PASS.value


def resolve_production_stage3_inputs(root: Path, wall_id: str, run_id: str) -> ProductionStage3Inputs:
    """Fail closed unless the named wall_build run is validated and self-identifying."""
    if not _safe_run_id(run_id):
        raise ProductionStage3BindError(REASON_UNSAFE_RUN_ID, f"unsafe runId {run_id!r}")
    run_dir = wall_build_run_dir(root, wall_id, run_id)
    if not run_dir.is_dir():
        raise ProductionStage3BindError(REASON_RUN_NOT_FOUND, f"missing wall_build run {run_id}")
    report = _read_json(run_dir / "wall_build_report.json")
    if report is None:
        raise ProductionStage3BindError(REASON_RUN_NOT_FOUND, "missing wall_build_report.json")
    if report.get("wallId") != wall_id:
        raise ProductionStage3BindError(REASON_WALL_ID_MISMATCH, "report.wallId does not match requested wallId")
    if report.get("runId") != run_id:
        raise ProductionStage3BindError(REASON_RUN_ID_MISMATCH, "report.runId does not match requested runId")
    missing = [name for name in REQUIRED_AUTO_PASS_STAGES if not _stage_ok(report, name)]
    reconstruction = (report.get("stageStatuses") or {}).get(Stage.RECONSTRUCTION.value) or {}
    metric = (report.get("stageStatuses") or {}).get(Stage.METRIC_REGISTRATION.value) or {}
    if reconstruction.get("gateResult") != "PASS":
        missing.append("RECONSTRUCTION.gateResult")
    if metric.get("validationStatus") != "VALIDATED" or metric.get("sWallColmapWritten") is not True:
        missing.append("METRIC_REGISTRATION.VALIDATED")
    if missing:
        raise ProductionStage3BindError(
            REASON_GATES_NOT_PASS,
            f"validated wall_build run required; failed: {missing}",
        )

    colmap_dir = run_dir / "colmap"
    identity = load_provenance(colmap_dir)
    if not identity:
        raise ProductionStage3BindError(REASON_IDENTITY_NOT_PROVEN, "missing colmap_source_identity.json")
    if identity.get("wallId") != wall_id:
        raise ProductionStage3BindError(REASON_WALL_ID_MISMATCH, "identity.wallId mismatch")
    if identity.get("provenanceOrigin") != PROVENANCE_ORIGIN_RECONSTRUCTION_RUN:
        raise ProductionStage3BindError(REASON_IDENTITY_NOT_PROVEN, "COLMAP identity is not RECONSTRUCTION_RUN")
    recorded = identity.get("modelFingerprint")
    if not isinstance(recorded, str) or not recorded:
        raise ProductionStage3BindError(REASON_IDENTITY_NOT_PROVEN, "identity.modelFingerprint missing")
    relative = identity.get("selectedModelRelativePath") or SELECTED_MODEL_RELATIVE_PATH
    model_dir = resolve_recorded_model_dir(colmap_dir, relative)
    if model_dir is None or not model_dir.is_dir():
        raise ProductionStage3BindError(REASON_IDENTITY_NOT_PROVEN, "selected COLMAP model directory missing")
    live = model_fingerprint(model_dir)
    if live != recorded:
        raise ProductionStage3BindError(
            REASON_FINGERPRINT_MISMATCH,
            "live modelFingerprint does not match recorded identity",
        )

    sim3_path = run_dir / "metric_registration" / "S_wall_colmap.json"
    try:
        sim3 = load_sim3(sim3_path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ProductionStage3BindError(REASON_SIM3_NOT_VALIDATED, f"S_wall_colmap unreadable: {exc}") from exc
    if str(sim3.get("status") or "").upper() != "VALIDATED":
        raise ProductionStage3BindError(REASON_SIM3_NOT_VALIDATED, "S_wall_colmap is not VALIDATED")
    if sim3.get("wallId") != wall_id:
        raise ProductionStage3BindError(REASON_SIM3_PROVENANCE_NOT_PROVEN, "S_wall_colmap.wallId missing or mismatched")
    if sim3.get("wallBuildRunId") != run_id:
        raise ProductionStage3BindError(REASON_SIM3_PROVENANCE_NOT_PROVEN, "S_wall_colmap.wallBuildRunId missing or mismatched")
    sim3_fp = sim3.get("colmapModelFingerprint") or sim3.get("modelFingerprint")
    if sim3_fp != recorded:
        raise ProductionStage3BindError(
            REASON_SIM3_PROVENANCE_NOT_PROVEN,
            "S_wall_colmap COLMAP fingerprint missing or mismatched",
        )

    return ProductionStage3Inputs(
        wall_id=wall_id,
        run_id=run_id,
        run_dir=run_dir,
        colmap_dir=colmap_dir,
        model_dir=model_dir,
        sim3_path=sim3_path,
        model_fingerprint=live,
        identity=identity,
        report=report,
        sim3=sim3,
    )
