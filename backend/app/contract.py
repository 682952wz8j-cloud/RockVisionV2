"""Cloud Asset Contract v1 identifiers, ID rules, and manifest validation."""

from __future__ import annotations

import re

CATALOG_SCHEMA = "cragpal.wall-catalog.v1"
MANIFEST_SCHEMA = "cragpal.wall-manifest.v1"
PROMOTION_SCHEMA = "cragpal.wall-promotion.v1"
PROMOTIONS_PREFIX = "published/promotions/"

# Canonical persisted environments. Align with localization-package vocabulary.
# Missing environment is unspecified / legacy compatibility, never production.
ENVIRONMENT_PRODUCTION = "production"
ENVIRONMENT_DEVELOPMENT_TEST = "development_test"
CLASSIFIED_ENVIRONMENTS = frozenset({ENVIRONMENT_PRODUCTION, ENVIRONMENT_DEVELOPMENT_TEST})

AUDIENCE_PRODUCTION = "PRODUCTION"
AUDIENCE_DEBUG_TEST = "DEBUG_TEST"

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
RELEASE_ID_RE = re.compile(r"^r[0-9]{6}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

FORBIDDEN_ID_SUBSTRINGS = ("..", "/", "\\", ":", "@")


class ContractError(ValueError):
    """Caller-supplied identifier or stored contract document is invalid."""


def is_safe_id(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if any(token in value for token in FORBIDDEN_ID_SUBSTRINGS):
        return False
    return SAFE_ID_RE.fullmatch(value) is not None


def is_release_id(value: str) -> bool:
    return isinstance(value, str) and RELEASE_ID_RE.fullmatch(value) is not None


def require_wall_id(wall_id: str) -> str:
    if not is_safe_id(wall_id):
        raise ContractError("invalid wallId")
    return wall_id


def require_asset_id(asset_id: str) -> str:
    if not is_safe_id(asset_id):
        raise ContractError("invalid assetId")
    return asset_id


def require_release_id(release_id: str) -> str:
    if not is_release_id(release_id):
        raise ContractError("invalid releaseId")
    return release_id


def published_catalog_key() -> str:
    return "published/catalog.json"


def published_promotions_prefix() -> str:
    return PROMOTIONS_PREFIX


def published_promotion_key(wall_id: str, release_id: str) -> str:
    require_wall_id(wall_id)
    require_release_id(release_id)
    return f"{PROMOTIONS_PREFIX}{wall_id}/{release_id}.json"


def parse_published_promotion_key(key: str) -> tuple[str, str]:
    """Accept only published/promotions/<wallId>/<releaseId>.json."""
    if not isinstance(key, str) or not key.startswith(PROMOTIONS_PREFIX):
        raise ContractError("unexpected promotion object key")
    rest = key[len(PROMOTIONS_PREFIX) :]
    parts = rest.split("/")
    if len(parts) != 2 or not parts[1].endswith(".json"):
        raise ContractError("unexpected promotion object key")
    wall_id, filename = parts
    release_id = filename[: -len(".json")]
    expected = published_promotion_key(wall_id, release_id)
    if key != expected:
        raise ContractError("unexpected promotion object key")
    return wall_id, release_id


def empty_catalog() -> dict:
    return {"schema": CATALOG_SCHEMA, "walls": []}


def classified_environment_from_payload(payload: dict) -> str | None:
    """Decode additive environment.

    Missing key → unspecified (None). Never treat missing as production.
    Present unknown / non-canonical value → fail closed.
    """
    if "environment" not in payload:
        return None
    value = payload["environment"]
    if value not in CLASSIFIED_ENVIRONMENTS:
        raise ContractError("invalid environment")
    return value


def catalog_entry(*, wall_id: str, name: str, latest_release_id: str, environment: str | None) -> dict:
    entry = {
        "wallId": wall_id,
        "name": name,
        "latestReleaseId": latest_release_id,
    }
    if environment is not None:
        if environment not in CLASSIFIED_ENVIRONMENTS:
            raise ContractError("invalid environment")
        entry["environment"] = environment
    return entry


def published_manifest_key(wall_id: str, release_id: str) -> str:
    require_wall_id(wall_id)
    require_release_id(release_id)
    return f"published/{wall_id}/{release_id}/manifest.json"


def published_asset_key(wall_id: str, release_id: str, asset_id: str) -> str:
    require_wall_id(wall_id)
    require_release_id(release_id)
    require_asset_id(asset_id)
    return f"published/{wall_id}/{release_id}/assets/{asset_id}"


def assert_manifest_identity(payload: dict, wall_id: str, release_id: str) -> dict:
    """Reject a stored manifest whose identity does not match the requested release."""
    payload = validate_manifest(payload)
    require_wall_id(wall_id)
    require_release_id(release_id)
    if payload["wallId"] != wall_id:
        raise ContractError("manifest.wallId does not match requested wallId")
    if payload["releaseId"] != release_id:
        raise ContractError("manifest.releaseId does not match requested releaseId")
    return payload


def validate_catalog(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ContractError("catalog must be an object")
    if payload.get("schema") != CATALOG_SCHEMA:
        raise ContractError("catalog schema is not cragpal.wall-catalog.v1")
    walls = payload.get("walls")
    if not isinstance(walls, list):
        raise ContractError("catalog.walls must be an array")
    seen: set[str] = set()
    for item in walls:
        if not isinstance(item, dict):
            raise ContractError("catalog wall entry must be an object")
        wall_id = require_wall_id(str(item.get("wallId") or ""))
        if wall_id in seen:
            raise ContractError("duplicate wallId in catalog")
        seen.add(wall_id)
        if not isinstance(item.get("name"), str) or not item["name"]:
            raise ContractError("catalog wall name is required")
        require_release_id(str(item.get("latestReleaseId") or ""))
        classified_environment_from_payload(item)
    return payload


def validate_manifest(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ContractError("manifest must be an object")
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise ContractError("manifest schema is not cragpal.wall-manifest.v1")
    require_wall_id(str(payload.get("wallId") or ""))
    require_release_id(str(payload.get("releaseId") or ""))
    if not isinstance(payload.get("createdAt"), str) or not payload["createdAt"]:
        raise ContractError("manifest.createdAt is required")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ContractError("manifest.assets must be an array")
    seen: set[str] = set()
    for item in assets:
        if not isinstance(item, dict):
            raise ContractError("manifest asset entry must be an object")
        asset_id = require_asset_id(str(item.get("assetId") or ""))
        if asset_id in seen:
            raise ContractError("duplicate assetId in release")
        seen.add(asset_id)
        if not isinstance(item.get("type"), str) or not item["type"]:
            raise ContractError("asset.type is required")
        if not isinstance(item.get("required"), bool):
            raise ContractError("asset.required must be a boolean")
        sha = item.get("sha256")
        if not isinstance(sha, str) or SHA256_RE.fullmatch(sha) is None:
            raise ContractError("asset.sha256 must be 64 lowercase hex characters")
        bytes_value = item.get("bytes")
        if not isinstance(bytes_value, int) or isinstance(bytes_value, bool) or bytes_value < 0:
            raise ContractError("asset.bytes must be a non-negative integer")
    return payload
