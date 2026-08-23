#!/usr/bin/env python3
"""Unified RockVision offline entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.colmap.cli import run_reconstruct  # noqa: E402
from offline.ingestion.cli import main as ingest_main  # noqa: E402
from offline.ingestion.pipeline import repo_root_from  # noqa: E402
from offline.metric_registration.cli import run_register  # noqa: E402
from offline.qualification.cli import run_qualify  # noqa: E402


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rockvision", description="RockVision offline tools")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest_cmd = sub.add_parser("ingest", help="Gate 1A: scan incoming/wall_<id>/")
    ingest_cmd.add_argument("wall_id")
    qualify_cmd = sub.add_parser("qualify", help="Gate 1B: qualify source data and coordinates")
    qualify_cmd.add_argument("wall_id")
    reconstruct_cmd = sub.add_parser("reconstruct", help="COLMAP sparse reconstruction on qualified DJI images")
    reconstruct_cmd.add_argument("wall_id")
    register_cmd = sub.add_parser("register", help="Metric Registration Gate: solve and validate S_wall_colmap")
    register_cmd.add_argument("wall_id")
    args = parser.parse_args(argv)
    repo = root or repo_root_from(Path(__file__))
    if args.command == "ingest":
        return ingest_main(["ingest", args.wall_id], root=repo)
    if args.command == "qualify":
        return run_qualify(args.wall_id, repo)
    if args.command == "reconstruct":
        return run_reconstruct(args.wall_id, repo)
    if args.command == "register":
        return run_register(args.wall_id, repo)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(root=ROOT))
