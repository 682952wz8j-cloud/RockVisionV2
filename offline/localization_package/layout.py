"""Deterministic local Production Localization Package paths.

Never writes under published/ or COS key layout.
"""

from __future__ import annotations

from pathlib import Path

from .schema import (
    EVIDENCE_COLMAP_IDENTITY,
    EVIDENCE_FREEZE,
    EVIDENCE_HEIGHT,
    EVIDENCE_POSITIONING,
    EVIDENCE_SELECTION,
)


def packages_root(repo: Path) -> Path:
    return repo / "offline" / "packages"


def package_dir(repo: Path, wall_id: str, release_id: str) -> Path:
    return packages_root(repo) / wall_id / release_id


def package_json_path(root: Path) -> Path:
    return root / "package.json"


def cloud_manifest_path(root: Path) -> Path:
    return root / "cloud-manifest.json"


def assets_dir(root: Path) -> Path:
    return root / "assets"


def evidence_dir(root: Path) -> Path:
    return root / "evidence"


def asset_path(root: Path, asset_id: str) -> Path:
    return assets_dir(root) / asset_id


def evidence_path(root: Path, name: str) -> Path:
    return evidence_dir(root) / name


def required_evidence_names() -> tuple[str, ...]:
    return (
        EVIDENCE_SELECTION,
        EVIDENCE_POSITIONING,
        EVIDENCE_HEIGHT,
        EVIDENCE_COLMAP_IDENTITY,
        EVIDENCE_FREEZE,
    )
