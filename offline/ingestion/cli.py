from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import ingest, repo_root_from
from .report import print_console_summary
from .types import RunResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rockvision",
        description="RockVision offline tools. Gate 1A: raw data ingestion.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ingest_cmd = sub.add_parser("ingest", help="Scan incoming/wall_<id>/ and write an inventory")
    ingest_cmd.add_argument("wall_id", help="Wall folder name, for example wall_jiulongfeng_01")
    return parser


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "ingest":
        parser.error("only the ingest command is available in Gate 1A")
    repo = root or repo_root_from(Path(__file__))
    summary = ingest(args.wall_id, repo)
    print_console_summary(summary)
    dest = repo / "offline" / "work" / args.wall_id / "ingestion"
    print(f"Wrote {dest / 'inventory.json'}")
    print(f"Wrote {dest / 'validation_report.md'}")
    return 0 if summary.result != RunResult.FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
