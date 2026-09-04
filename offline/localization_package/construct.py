"""Write a local package candidate without claiming PACKAGE_READY.

Does not publish. Does not talk to COS.
"""

from __future__ import annotations

import json
from pathlib import Path

from .layout import asset_path, cloud_manifest_path, evidence_path, package_json_path
from .schema import STATE_CONSTRUCTED, STATE_NOT_PACKAGE_READY


def write_package_candidate(
    root: Path,
    *,
    package: dict,
    cloud_manifest: dict,
    assets: dict[str, bytes],
    evidence: dict[str, dict | bytes],
) -> Path:
    """Copy files into a local package directory. packageState must not be PACKAGE_READY."""
    if package.get("packageState") not in {STATE_CONSTRUCTED, STATE_NOT_PACKAGE_READY}:
        raise ValueError("construction must not label PACKAGE_READY")
    if package.get("capabilities", {}).get("localizationReady") is True:
        raise ValueError("construction must not claim localizationReady")
    root.mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "evidence").mkdir(parents=True, exist_ok=True)
    package_json_path(root).write_text(json.dumps(package, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cloud_manifest_path(root).write_text(
        json.dumps(cloud_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for asset_id, data in assets.items():
        asset_path(root, asset_id).write_bytes(data)
    for name, payload in evidence.items():
        dest = evidence_path(root, name)
        if isinstance(payload, bytes):
            dest.write_bytes(payload)
        else:
            dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return root
