from __future__ import annotations

import json
from pathlib import Path


def _dumps(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dumps(data) + "\n", encoding="utf-8")


def render_reconstruction_report(payload: dict) -> str:
    features = payload.get("features") or {}
    matching = payload.get("matching") or {}
    sparse = payload.get("sparse") or {}
    obs = payload.get("observations") or {}
    unreg = payload.get("unregisteredImages") or []
    lines = [
        "# COLMAP Sparse Reconstruction Report",
        "",
        f"Wall ID: {payload.get('wallId')}",
        f"Engine: {payload.get('engine')}",
        f"Incoming immutable: {'PASS' if payload.get('incomingUnchanged') else 'FAIL'}",
        f"Gate result: {payload.get('gateResult')}",
        "",
        "## Images",
        "",
        f"source images: {payload.get('sourceImages')}",
        f"registered images: {payload.get('registeredImages')}",
        f"unregistered images: {payload.get('unregisteredImagesCount')}",
        f"registration rate: {payload.get('registrationRate')}",
        "",
        "Unregistered filenames:",
    ]
    if unreg:
        lines.extend(f"- {name}" for name in unreg)
    else:
        lines.append("- none")
    kp = (features.get("keypoints") or {})
    lines.extend(
        [
            "",
            "## Features",
            "",
            f"extraction success: {features.get('success')}",
            f"extraction failed: {features.get('failed')}",
            f"keypoints min / median / max: {kp.get('min')} / {kp.get('median')} / {kp.get('max')}",
            f"descriptors min / median / max: {(features.get('descriptors') or {}).get('min')} / {(features.get('descriptors') or {}).get('median')} / {(features.get('descriptors') or {}).get('max')}",
            "",
            "## Matching",
            "",
            f"strategy: {matching.get('strategy')}",
            f"attempted pairs: {matching.get('attemptedPairs')}",
            f"verified pairs: {matching.get('verifiedPairs')}",
            f"inliers min / median / max: {(matching.get('inliers') or {}).get('min')} / {(matching.get('inliers') or {}).get('median')} / {(matching.get('inliers') or {}).get('max')}",
            f"total inlier matches: {matching.get('totalInlierMatches')}",
            "",
            "## Sparse Points",
            "",
            f"models: {payload.get('modelCount')}",
            f"selected model: {payload.get('selectedModelId')}",
            f"total points3D: {sparse.get('points3D')}",
            f"observations: {sparse.get('observations')}",
            f"mean track length: {sparse.get('meanTrackLength')}",
            f"median track length: {(sparse.get('trackLength') or {}).get('median')}",
            f"mean reprojection error: {(sparse.get('reprojectionError') or {}).get('mean')}",
            f"median reprojection error: {(sparse.get('reprojectionError') or {}).get('median')}",
            "",
            "## 2D ↔ 3D Observations",
            "",
            f"images with valid point3D observations: {obs.get('imagesWithObservations')}",
            f"total 2D→3D observations: {obs.get('total')}",
            f"per image min / median / max: {(obs.get('stats') or {}).get('min')} / {(obs.get('stats') or {}).get('median')} / {(obs.get('stats') or {}).get('max')}",
            "",
            "## Camera Model",
            "",
            _dumps(payload.get("cameraModel")),
            "",
            "## S_wall_colmap",
            "",
            "NOT COMPUTED",
            "",
            "Sparse Reconstruction and Metric Registration are separate. This gate does not solve Sim(3).",
            "",
            "## Problems",
            "",
        ]
    )
    problems = payload.get("problems") or []
    if problems:
        lines.extend(f"- {item}" for item in problems)
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)
