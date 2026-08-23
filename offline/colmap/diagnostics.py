"""Lightweight diagnostic exports from a COLMAP reconstruction. No extra deps."""

from __future__ import annotations

import json
from pathlib import Path


def write_diagnostics(reconstruction, dest: Path, pair_graph: list[dict] | None = None) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    cameras_path = dest / "registered_camera_positions.txt"
    graph_path = dest / "image_registration_graph.json"
    ply_path = dest / "sparse_points.ply"

    lines = ["# name x y z"]
    for image_id in reconstruction.reg_image_ids():
        image = reconstruction.image(image_id)
        center = image.projection_center()
        lines.append(f"{image.name} {float(center[0])} {float(center[1])} {float(center[2])}")
    cameras_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    reconstruction.export_PLY(str(ply_path))
    graph_path.write_text(
        json.dumps({"pairs": pair_graph or [], "note": "visual matches only; no RTK-made pairs"}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return {
        "cameraPositions": str(cameras_path),
        "sparsePly": str(ply_path),
        "registrationGraph": str(graph_path),
    }
