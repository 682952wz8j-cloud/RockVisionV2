from __future__ import annotations

from pathlib import Path

from .pipeline import reconstruct


def run_reconstruct(wall_id: str, root: Path) -> int:
    payload = reconstruct(wall_id, root)
    dest = root / "offline" / "work" / wall_id / "colmap"
    print(f"Wall ID: {wall_id}")
    print(f"Source images: {payload.get('sourceImages')}")
    print(f"Registered: {payload.get('registeredImages')}")
    print(f"Registration rate: {payload.get('registrationRate')}")
    print(f"S_wall_colmap: {payload.get('sWallColmap')}")
    print(f"Gate result: {payload.get('gateResult')}")
    if payload.get("errors"):
        for err in payload["errors"]:
            print("ERROR:", err)
    print(f"Wrote {dest / 'reconstruction_report.md'}")
    return 0 if payload.get("gateResult") != "FAIL" and payload.get("incomingUnchanged", False) else 1
