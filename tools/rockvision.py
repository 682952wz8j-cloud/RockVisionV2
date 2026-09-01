#!/usr/bin/env python3
"""Unified RockVision offline entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.ingestion.pipeline import repo_root_from  # noqa: E402


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rockvision", description="RockVision offline tools")
    sub = parser.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser(
        "build",
        help="Phase 1: gate-aware wall build (discovery/preflight/ingest/qualify, then stop)",
    )
    build_cmd.add_argument("wall_id")
    ingest_cmd = sub.add_parser("ingest", help="Gate 1A: scan incoming/wall_<id>/")
    ingest_cmd.add_argument("wall_id")
    qualify_cmd = sub.add_parser("qualify", help="Gate 1B: qualify source data and coordinates")
    qualify_cmd.add_argument("wall_id")
    reconstruct_cmd = sub.add_parser("reconstruct", help="COLMAP sparse reconstruction on qualified DJI images")
    reconstruct_cmd.add_argument("wall_id")
    register_cmd = sub.add_parser("register", help="Metric Registration Gate: solve and validate S_wall_colmap")
    register_cmd.add_argument("wall_id")
    match_cmd = sub.add_parser(
        "reference-match",
        help="Gate 3C: OpenCV reference SIFT, 2px association, freeze artifact, same-image/LOO (stops before Swift)",
    )
    match_cmd.add_argument("wall_id")
    pnp_cmd = sub.add_parser("pnp", help="Gate 3D: pinned OpenCV 4.14.0 single-frame PnP (offline)")
    pnp_cmd.add_argument("--self-test", action="store_true")
    pnp_cmd.add_argument("--session", help="Field Test samples.jsonl (not gate3b_20260824_155143)")
    pnp_cmd.add_argument("--wall-id", default="wall_jiulongfeng_01")
    stage2_dev_cmd = sub.add_parser(
        "stage2-dev",
        help="DEVELOPMENT ONLY: Generic Stage 2 select/register-selected/reconstruct-selected. Not ordinary production build.",
    )
    stage2_dev_cmd.add_argument(
        "stage2_dev_action",
        choices=["select", "register-selected", "reconstruct-selected"],
    )
    stage2_dev_cmd.add_argument("wall_id")
    stage2_dev_cmd.add_argument(
        "--dev-workspace",
        help="Required in tests; development workspace. Must not be a frozen Jiulongfeng work tree.",
    )
    stage2_dev_cmd.add_argument("--colmap-dir", help="Existing COLMAP sparse directory for register-selected")
    stage2_dev_cmd.add_argument("--height-sfm-geo-desc", dest="height_sfm_geo_desc", default=None)
    stage2_dev_cmd.add_argument("--height-legacy-mrk", dest="height_legacy_mrk", default=None)
    verify_cmd = sub.add_parser(
        "verify",
        help="Run aggregated deterministic unit tests. Not a Gate PASS, FREEZE, or Stage advance.",
    )
    verify_cmd.add_argument(
        "--module",
        action="append",
        dest="verify_modules",
        help="Optional unittest module override. Repeatable. Default: existing offline.tests suite.",
    )
    args = parser.parse_args(argv)
    repo = root or repo_root_from(Path(__file__))
    if args.command == "build":
        from offline.wall_build.cli import run_build

        return run_build(args.wall_id, repo)
    if args.command == "ingest":
        from offline.ingestion.cli import main as ingest_main

        return ingest_main(["ingest", args.wall_id], root=repo)
    if args.command == "qualify":
        from offline.qualification.cli import run_qualify

        return run_qualify(args.wall_id, repo)
    if args.command == "reconstruct":
        from offline.colmap.cli import run_reconstruct

        return run_reconstruct(args.wall_id, repo)
    if args.command == "register":
        from offline.metric_registration.cli import run_register

        return run_register(args.wall_id, repo)
    if args.command == "reference-match":
        from offline.reference_matching.cli import run_reference_match

        return run_reference_match(args.wall_id, repo)
    if args.command == "pnp":
        from offline.pnp.cli import run_pnp

        return run_pnp(args, repo)
    if args.command == "stage2-dev":
        from offline.stage2_dev.cli import run_stage2_dev

        return run_stage2_dev(args, repo)
    if args.command == "verify":
        from offline.verify import run_verify

        return run_verify(args.verify_modules)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(root=ROOT))
