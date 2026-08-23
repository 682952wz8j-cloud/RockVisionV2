from __future__ import annotations

from pathlib import Path

from .pipeline import output_dir, register


def run_register(wall_id: str, root: Path) -> int:
    payload = register(wall_id, root)
    dest = output_dir(root, wall_id)
    print(f"Wall ID: {wall_id}")
    print(f"Correspondences: {payload.get('correspondenceCount')}")
    print(f"S_wall_colmap: {payload.get('validationStatus')}")
    print(f"Gate result: {payload.get('gateResult')}")
    if payload.get("errors"):
        for err in payload["errors"]:
            print("ERROR:", err)
    print(f"Wrote {dest / 'metric_registration_report.md'}")
    return 0 if payload.get("gateResult") != "FAIL" and payload.get("incomingUnchanged", False) else 1
