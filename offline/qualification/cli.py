from __future__ import annotations

from pathlib import Path

from .pipeline import qualify


def run_qualify(wall_id: str, root: Path) -> int:
    payload = qualify(wall_id, root)
    dest = root / "offline" / "work" / wall_id / "qualification"
    if payload.get("result") == "FAIL":
        print("Qualification: FAIL")
        for err in payload.get("errors") or []:
            print("ERROR:", err)
        return 1
    print(f"Wall ID: {wall_id}")
    print(f"Incoming immutable: {'PASS' if payload.get('incomingUnchanged') else 'FAIL'}")
    images = payload["sourceImages"]
    print(f"Original camera images: {images['byRole'].get('originalCameraImage', 0)}")
    print(f"COLMAP source images: {len(images['colmapSourceImages'])}")
    print(f"Wrote {dest / 'qualification_report.md'}")
    print(f"Wrote {dest / 'coordinate_provenance.md'}")
    return 0 if payload.get("incomingUnchanged") else 1
