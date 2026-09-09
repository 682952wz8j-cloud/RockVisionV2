"""Bind route ingestion to one explicit validated wall_build run + freeze."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from offline.reference_matching.production_run import (
    ProductionStage3BindError,
    ProductionStage3Inputs,
    resolve_production_stage3_inputs,
    wall_build_run_dir,
)
from offline.wall_build.stage3_run import freeze_bound, freeze_dir

from .schema import REASON_BIND_FAILED, REASON_PROVENANCE


class RouteBindError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RouteBind:
    wall_id: str
    run_id: str
    run_dir: Path
    model_fingerprint: str
    freeze_directory: Path
    localization_package_dir: Path
    stage3: ProductionStage3Inputs
    freeze: dict


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def bind_production_run(
    root: Path,
    wall_id: str,
    run_id: str,
    *,
    expected_fingerprint: str,
) -> RouteBind:
    if not isinstance(expected_fingerprint, str) or not expected_fingerprint:
        raise RouteBindError(REASON_BIND_FAILED, "colmapModelFingerprint is required")
    try:
        stage3 = resolve_production_stage3_inputs(root, wall_id, run_id)
    except ProductionStage3BindError as exc:
        raise RouteBindError(exc.code, str(exc)) from exc
    if stage3.model_fingerprint != expected_fingerprint:
        raise RouteBindError(
            REASON_PROVENANCE,
            "live colmapModelFingerprint does not match requested fingerprint",
        )
    run_dir = wall_build_run_dir(root, wall_id, run_id)
    if not freeze_bound(run_dir, wall_id=wall_id, run_id=run_id):
        raise RouteBindError(REASON_BIND_FAILED, "Stage 3 freeze is not bound to this run")
    dest = freeze_dir(run_dir)
    freeze = _read_json(dest / "freeze.json")
    if freeze is None:
        raise RouteBindError(REASON_BIND_FAILED, "missing freeze.json")
    if freeze.get("wallId") != wall_id or freeze.get("wallBuildRunId") != run_id:
        raise RouteBindError(REASON_PROVENANCE, "freeze identity does not match wallId/runId")
    if freeze.get("colmapModelFingerprint") != expected_fingerprint:
        raise RouteBindError(REASON_PROVENANCE, "freeze.colmapModelFingerprint mismatch")
    loc = run_dir / "localization_package"
    if not loc.is_dir():
        raise RouteBindError(REASON_BIND_FAILED, "missing localization_package on bound run")
    return RouteBind(
        wall_id=wall_id,
        run_id=run_id,
        run_dir=run_dir,
        model_fingerprint=stage3.model_fingerprint,
        freeze_directory=dest,
        localization_package_dir=loc,
        stage3=stage3,
        freeze=freeze,
    )
