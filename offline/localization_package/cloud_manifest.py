"""Local cloud-manifest.json candidate. Compatible with cragpal.wall-manifest.v1.

Does not upload. Does not change backend or iOS runtime behavior.
"""

from __future__ import annotations

import re

from .package_schema import is_release_id, is_safe_id
from .schema import (
    CLOUD_MANIFEST_SCHEMA,
    ReasonCode,
    REQUIRED_ASSET_TYPES,
    TYPE_DESCRIPTORS,
    TYPE_LANDMARKS,
    TYPE_S_WALL_COLMAP,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CloudManifestError(ValueError):
    def __init__(self, code: ReasonCode, message: str):
        super().__init__(message)
        self.code = code


def decode_cloud_manifest_candidate(payload: object, *, wall_id: str, release_id: str) -> dict:
    if not isinstance(payload, dict):
        raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, "cloud-manifest.json must be an object")
    if payload.get("schema") != CLOUD_MANIFEST_SCHEMA:
        raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, "schema must be cragpal.wall-manifest.v1")
    if not is_safe_id(str(payload.get("wallId") or "")):
        raise CloudManifestError(ReasonCode.INVALID_WALL_ID, "invalid cloud-manifest wallId")
    if not is_release_id(str(payload.get("releaseId") or "")):
        raise CloudManifestError(ReasonCode.INVALID_RELEASE_ID, "invalid cloud-manifest releaseId")
    if payload["wallId"] != wall_id:
        raise CloudManifestError(ReasonCode.WALL_ID_MISMATCH, "cloud-manifest wallId mismatch")
    if payload["releaseId"] != release_id:
        raise CloudManifestError(ReasonCode.RELEASE_ID_MISMATCH, "cloud-manifest releaseId mismatch")
    if not isinstance(payload.get("createdAt"), str) or not payload["createdAt"]:
        raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, "createdAt is required")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, "assets must be an array")
    seen: set[str] = set()
    types: dict[str, dict] = {}
    for item in assets:
        if not isinstance(item, dict):
            raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, "asset entry must be an object")
        asset_id = str(item.get("assetId") or "")
        if not is_safe_id(asset_id):
            raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, "invalid assetId")
        if asset_id in seen:
            raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, "duplicate assetId")
        seen.add(asset_id)
        asset_type = item.get("type")
        if not isinstance(asset_type, str) or not asset_type:
            raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, "asset.type is required")
        if item.get("required") is not True:
            raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, "localization assets must be required=true")
        sha = item.get("sha256")
        if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
            raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, "asset.sha256 must be 64 lowercase hex")
        bytes_value = item.get("bytes")
        if not isinstance(bytes_value, int) or isinstance(bytes_value, bool) or bytes_value < 0:
            raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, "asset.bytes must be a non-negative integer")
        if asset_type in types:
            raise CloudManifestError(ReasonCode.CLOUD_MANIFEST_INVALID, f"duplicate semantic type {asset_type}")
        types[asset_type] = item
    for required in REQUIRED_ASSET_TYPES:
        if required not in types:
            raise CloudManifestError(ReasonCode.MISSING_REQUIRED_ASSET, f"missing required type {required}")
    if types[TYPE_DESCRIPTORS]["type"] != TYPE_DESCRIPTORS:
        raise CloudManifestError(ReasonCode.DESCRIPTORS_REQUIRED, "descriptors type missing")
    if types[TYPE_LANDMARKS]["type"] != TYPE_LANDMARKS:
        raise CloudManifestError(ReasonCode.LANDMARKS_REQUIRED, "landmarks type missing")
    if types[TYPE_S_WALL_COLMAP]["type"] != TYPE_S_WALL_COLMAP:
        raise CloudManifestError(ReasonCode.METRIC_SIM3_REQUIRED, "S_wall_colmap type missing")
    return payload


def local_cloud_manifest(
    *,
    wall_id: str,
    release_id: str,
    created_at: str,
    descriptors: dict,
    landmarks: dict,
    metric: dict,
) -> dict:
    """Local candidate only. Not uploaded. Not consumed by current iOS."""
    return {
        "schema": CLOUD_MANIFEST_SCHEMA,
        "wallId": wall_id,
        "releaseId": release_id,
        "createdAt": created_at,
        "assets": [
            _manifest_asset(descriptors, TYPE_DESCRIPTORS),
            _manifest_asset(landmarks, TYPE_LANDMARKS),
            _manifest_asset(metric, TYPE_S_WALL_COLMAP),
        ],
    }


def _manifest_asset(spec: dict, expected_type: str) -> dict:
    return {
        "assetId": spec["assetId"],
        "type": expected_type,
        "required": True,
        "sha256": spec["sha256"],
        "bytes": spec["bytes"],
    }
