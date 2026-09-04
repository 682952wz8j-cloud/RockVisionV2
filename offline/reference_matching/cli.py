from __future__ import annotations

from pathlib import Path

from .pipeline import build_reference_matching, output_dir
from .production_run import wall_build_run_dir


def run_reference_match(wall_id: str, root: Path, *, run_id: str | None = None) -> int:
    payload = build_reference_matching(wall_id, root, run_id=run_id)
    dest = payload.get("outputDirectory")
    if dest:
        dest_path = Path(dest)
    elif run_id and ".." not in run_id and "/" not in run_id and "\\" not in run_id:
        dest_path = output_dir(root, wall_id, run_dir=wall_build_run_dir(root, wall_id, run_id))
    else:
        dest_path = output_dir(root, wall_id)
    print(f"Wall ID: {wall_id}")
    if run_id:
        print(f"wall_build runId: {run_id}")
        print("productionBound: True")
        print("legacyFallback: False")
    print(f"OpenCV: {(payload.get('opencv') or {}).get('status')}")
    print(f"Stage: {payload.get('stage')}")
    print(f"Gate result: {payload.get('gateResult')}")
    print(f"STOP before Swift: {payload.get('stopBeforeSwift')}")
    if payload.get("reasonCode"):
        print(f"Reason: {payload.get('reasonCode')}")
    if payload.get("errors"):
        for err in payload["errors"]:
            print("ERROR:", err)
    for problem in payload.get("problems") or []:
        print("PROBLEM:", problem)
    print(f"Wrote {dest_path / 'compatibility_report.md'}")
    if payload.get("gateResult") == "STOP" or payload.get("errors"):
        return 1
    return 0
