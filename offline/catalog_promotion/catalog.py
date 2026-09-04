"""cragpal.wall-catalog.v1 decode/encode. Compatible with backend/iOS contract."""

from __future__ import annotations

import json

from offline.localization_package.package_schema import is_release_id, is_safe_id

CATALOG_SCHEMA = "cragpal.wall-catalog.v1"


class CatalogError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def encode_catalog(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def empty_catalog() -> dict:
    return {"schema": CATALOG_SCHEMA, "walls": []}


def decode_catalog(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise CatalogError("CATALOG_INVALID", "catalog must be an object")
    if payload.get("schema") != CATALOG_SCHEMA:
        raise CatalogError("CATALOG_SCHEMA_UNSUPPORTED", "catalog schema is not cragpal.wall-catalog.v1")
    walls = payload.get("walls")
    if not isinstance(walls, list):
        raise CatalogError("CATALOG_INVALID", "catalog.walls must be an array")
    seen: set[str] = set()
    for item in walls:
        if not isinstance(item, dict):
            raise CatalogError("CATALOG_INVALID", "catalog wall entry must be an object")
        wall_id = str(item.get("wallId") or "")
        if not is_safe_id(wall_id):
            raise CatalogError("CATALOG_INVALID", "invalid catalog wallId")
        if wall_id in seen:
            raise CatalogError("CATALOG_INVALID", "duplicate wallId in catalog")
        seen.add(wall_id)
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise CatalogError("CATALOG_INVALID", "catalog wall name is required")
        release_id = str(item.get("latestReleaseId") or "")
        if not is_release_id(release_id):
            raise CatalogError("CATALOG_INVALID", "invalid catalog latestReleaseId")
    return payload


def release_ordinal(release_id: str) -> int:
    if not is_release_id(release_id):
        raise CatalogError("INVALID_RELEASE_ID", "invalid releaseId")
    return int(release_id[1:])
