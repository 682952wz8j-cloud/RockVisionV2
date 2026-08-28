"""CLI for `rockvision stage2-dev`. Development-only. Not production build."""

from __future__ import annotations

from pathlib import Path

from .runner import run_register_selected, run_reconstruct_selected, run_select


def run_stage2_dev(args, root: Path) -> int:
    wall_id = args.wall_id
    if not args.dev_workspace:
        print("ERROR: --dev-workspace is required for stage2-dev.")
        print("Do not use frozen Jiulongfeng colmap/ or metric_registration/ trees as output.")
        return 2
    workspace = Path(args.dev_workspace)
    action = args.stage2_dev_action
    print("DEVELOPMENT ONLY — Generic Stage 2")
    print("Ordinary ./rockvision build does NOT run reconstruction or metric registration.")
    if action == "select":
        artifact = run_select(wall_id, root, workspace=workspace)
        print(f"Wall ID: {wall_id}")
        print(f"selectionStatus: {artifact.get('selectionStatus')}")
        print(f"outputFrame: {artifact.get('outputFrame')}")
        print(f"wallMetricMetersProvenance: {artifact.get('wallMetricMetersProvenance')}")
        print(f"Wrote {workspace / 'stage2_input_selection.json'}")
        return 0 if artifact.get("selectionStatus") == "AUTO_PASS" else 2
    if action == "register-selected":
        if not args.colmap_dir:
            print("ERROR: --colmap-dir is required for register-selected")
            return 2
        payload = run_register_selected(
            wall_id,
            root,
            workspace=workspace,
            colmap_dir=Path(args.colmap_dir),
            height_sfm_geo_desc=args.height_sfm_geo_desc,
            height_legacy_mrk=args.height_legacy_mrk,
        )
        print(f"Wall ID: {wall_id}")
        print(f"Gate result: {payload.get('gateResult')}")
        print(f"scale: {payload.get('scale')}")
        print(f"Wrote {workspace / 'metric_registration'}")
        return 0 if payload.get("gateResult") != "FAIL" else 1
    if action == "reconstruct-selected":
        payload = run_reconstruct_selected(wall_id, root, workspace=workspace)
        print(f"Wall ID: {wall_id}")
        print(f"Gate result: {payload.get('gateResult')}")
        print(f"Wrote {workspace / 'colmap'}")
        print("productionBuildStage2Enabled: False")
        return 0 if payload.get("gateResult") != "FAIL" else 1
    print(f"unknown stage2-dev action {action}")
    return 2
