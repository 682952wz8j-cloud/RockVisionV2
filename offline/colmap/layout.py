"""Incoming layout checks for the COLMAP gate.

2026-08-23 captures must live under incoming/wall_<id>/. Loose copies at
incoming/ root are a STOP condition. This module never moves files.
"""

from __future__ import annotations

from pathlib import Path

DJI_CAPTURE_DIR = "DJI_202608231218_006_九龙峰"
IPHONE_CAPTURE_DIR = "0823 iphone拍摄"
REQUIRED_SESSION = "dji_20260823"


def check_incoming_layout(root: Path, wall_id: str) -> list[str]:
    incoming = root / "incoming"
    wall = incoming / wall_id
    errors: list[str] = []
    if (incoming / DJI_CAPTURE_DIR).is_dir():
        errors.append(
            f"loose capture still at incoming/{DJI_CAPTURE_DIR}; "
            "must be inside incoming/wall_<id>/ and must not be auto-moved"
        )
    if (incoming / IPHONE_CAPTURE_DIR).is_dir():
        errors.append(
            f"loose capture still at incoming/{IPHONE_CAPTURE_DIR}; "
            "must be inside incoming/wall_<id>/ and must not be auto-moved"
        )
    if not wall.is_dir():
        errors.append(f"incoming/{wall_id}/ does not exist")
        return errors
    if not (wall / DJI_CAPTURE_DIR).is_dir():
        errors.append(f"incoming/{wall_id}/{DJI_CAPTURE_DIR} is missing")
    return errors


def wall_incoming(root: Path, wall_id: str) -> Path:
    return root / "incoming" / wall_id


def output_dir(root: Path, wall_id: str) -> Path:
    return root / "offline" / "work" / wall_id / "colmap"


def normalize_wall_relative(relative_path: str) -> str:
    rel = relative_path.replace("\\", "/")
    while rel.startswith("../"):
        rel = rel[3:]
    if rel.startswith("./"):
        rel = rel[2:]
    return rel


def is_new_dji_relative(relative_path: str) -> bool:
    norm = normalize_wall_relative(relative_path)
    name = Path(norm).name.upper()
    return norm.startswith(f"{DJI_CAPTURE_DIR}/") and name.endswith((".JPG", ".JPEG"))
