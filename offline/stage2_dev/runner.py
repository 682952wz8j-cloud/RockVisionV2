"""Development-only Generic Stage 2 runner.

This is NOT ordinary production `./rockvision build`.
Production build now executes approved Generic Stage 2 itself.
stage2-dev remains a separate workspace tool.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from offline.colmap.pipeline import reconstruct
from offline.metric_registration.pipeline import register
from offline.stage2_capability import capability_fields
from offline.stage2_selection.artifact import write_selection_artifact
from offline.stage2_selection.select import select_stage2_inputs
from offline.stage2_selection.sources import Stage2SelectedSources, sources_from_selection

DEVELOPMENT_ONLY = True
NOT_PRODUCTION_BUILD = True
COMMAND_NAME = "stage2-dev"


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def default_dev_workspace(root: Path, wall_id: str) -> Path:
    return root / "offline" / "work" / wall_id / "stage2_dev" / _now_slug()


def _refuse_production_work_tree(root: Path, wall_id: str, workspace: Path, leaf: str) -> str | None:
    production = (root / "offline" / "work" / wall_id / leaf).resolve()
    dest = (workspace / leaf).resolve()
    if dest == production:
        return (
            f"stage2-dev must not write production {leaf} work tree {production}. "
            "Pass a separate --dev-workspace."
        )
    return None


def run_select(wall_id: str, root: Path, *, workspace: Path) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    artifact = select_stage2_inputs(wall_id, root, run_id=workspace.name)
    write_selection_artifact(workspace / "stage2_input_selection.json", artifact)
    (workspace / "DEVELOPMENT_ONLY.txt").write_text(
        "This directory is a Generic Stage 2 development workspace.\n"
        "Ordinary ./rockvision build now runs approved Generic Stage 2.\n"
        "stage2-dev remains a separate development workspace tool.\n",
        encoding="utf-8",
    )
    return artifact


def run_register_selected(
    wall_id: str,
    root: Path,
    *,
    workspace: Path,
    colmap_dir: Path,
    height_sfm_geo_desc: str | None = None,
    height_legacy_mrk: str | None = None,
    selection: dict | None = None,
) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    if selection is None:
        selection = select_stage2_inputs(wall_id, root, run_id=workspace.name)
        write_selection_artifact(workspace / "stage2_input_selection.json", selection)
    sources = sources_from_selection(selection)
    if sources is None:
        return {
            "wallId": wall_id,
            "gateResult": "FAIL",
            "validationStatus": "NOT VALIDATED",
            "errors": ["stage2 input selection is not AUTO_PASS"],
            "selectionStatus": selection.get("selectionStatus"),
            "developmentOnly": True,
            **capability_fields(),
        }
    if height_sfm_geo_desc or height_legacy_mrk:
        sources = Stage2SelectedSources(
            **{
                **sources.__dict__,
                "height_sfm_geo_desc": height_sfm_geo_desc,
                "height_legacy_mrk": height_legacy_mrk,
            }
        )
    blocked = _refuse_production_work_tree(root, wall_id, workspace, "metric_registration")
    if blocked:
        return {
            "wallId": wall_id,
            "gateResult": "FAIL",
            "errors": [blocked],
            "developmentOnly": True,
            **capability_fields(),
        }
    dest = workspace / "metric_registration"
    payload = register(
        wall_id,
        root,
        sources=sources,
        dest=dest,
        colmap_dir=colmap_dir,
    )
    payload["developmentOnly"] = True
    payload.update(capability_fields())
    payload["outputFrame"] = "WallLocal"
    payload["wallMetricMetersProvenance"] = "NOT_CLAIMED"
    return payload


def run_reconstruct_selected(
    wall_id: str,
    root: Path,
    *,
    workspace: Path,
    selection: dict | None = None,
) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    if selection is None:
        selection = select_stage2_inputs(wall_id, root, run_id=workspace.name)
        write_selection_artifact(workspace / "stage2_input_selection.json", selection)
    sources = sources_from_selection(selection)
    if sources is None:
        return {
            "wallId": wall_id,
            "gateResult": "FAIL",
            "errors": ["stage2 input selection is not AUTO_PASS"],
            "developmentOnly": True,
            **capability_fields(),
        }
    blocked = _refuse_production_work_tree(root, wall_id, workspace, "colmap")
    if blocked:
        return {
            "wallId": wall_id,
            "gateResult": "FAIL",
            "errors": [blocked],
            "developmentOnly": True,
            **capability_fields(),
        }
    dest = workspace / "colmap"
    payload = reconstruct(wall_id, root, sources=sources, dest=dest)
    payload["developmentOnly"] = True
    payload.update(capability_fields())
    return payload
