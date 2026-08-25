from __future__ import annotations

from pathlib import Path

from .pipeline import build_reference_matching, output_dir


def run_reference_match(wall_id: str, root: Path) -> int:
    payload = build_reference_matching(wall_id, root)
    dest = output_dir(root, wall_id)
    print(f"Wall ID: {wall_id}")
    print(f"OpenCV: {(payload.get('opencv') or {}).get('status')}")
    print(f"Stage: {payload.get('stage')}")
    print(f"Gate result: {payload.get('gateResult')}")
    print(f"STOP before Swift: {payload.get('stopBeforeSwift')}")
    if payload.get("errors"):
        for err in payload["errors"]:
            print("ERROR:", err)
    for problem in payload.get("problems") or []:
        print("PROBLEM:", problem)
    print(f"Wrote {dest / 'compatibility_report.md'}")
    if payload.get("gateResult") == "STOP" or payload.get("errors"):
        return 1
    return 0
