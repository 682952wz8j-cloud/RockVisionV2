"""Published COS key builders for publisher v1.

Duplicates Cloud Asset Contract v1 key layout without importing the
backend runtime store. Never writes catalog.json.
"""

from __future__ import annotations

from offline.localization_package.package_schema import is_release_id, is_safe_id

CATALOG_KEY = "published/catalog.json"
PROMOTIONS_PREFIX = "published/promotions/"


class PublisherKeyError(ValueError):
    """Unsafe wallId, releaseId, or assetId for a published key."""


def published_catalog_key() -> str:
    """Catalog key. Publisher v1 must never GET or PUT this path."""
    return CATALOG_KEY


def published_release_prefix(wall_id: str, release_id: str) -> str:
    _require_wall_id(wall_id)
    _require_release_id(release_id)
    return f"published/{wall_id}/{release_id}/"


def published_manifest_key(wall_id: str, release_id: str) -> str:
    return published_release_prefix(wall_id, release_id) + "manifest.json"


def published_asset_key(wall_id: str, release_id: str, asset_id: str) -> str:
    _require_wall_id(wall_id)
    _require_release_id(release_id)
    _require_asset_id(asset_id)
    return f"published/{wall_id}/{release_id}/assets/{asset_id}"


def published_promotion_key(wall_id: str, release_id: str) -> str:
    _require_wall_id(wall_id)
    _require_release_id(release_id)
    return f"{PROMOTIONS_PREFIX}{wall_id}/{release_id}.json"


def assert_not_catalog_key(key: str) -> str:
    if key == CATALOG_KEY or key.endswith("/catalog.json"):
        raise PublisherKeyError("publisher must not touch published/catalog.json")
    return key


def assert_not_promotion_key(key: str) -> str:
    if key.startswith(PROMOTIONS_PREFIX):
        raise PublisherKeyError("publisher must not write promotion records")
    return key


def _require_wall_id(wall_id: str) -> str:
    if not is_safe_id(wall_id):
        raise PublisherKeyError("invalid wallId")
    return wall_id


def _require_release_id(release_id: str) -> str:
    if not is_release_id(release_id):
        raise PublisherKeyError("invalid releaseId")
    return release_id


def _require_asset_id(asset_id: str) -> str:
    if not is_safe_id(asset_id):
        raise PublisherKeyError("invalid assetId")
    return asset_id
