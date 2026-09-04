"""Fail-closed catalog promotion.

Validates an already-published immutable release, then compare-and-swap
published/catalog.json. Never rewrites assets or manifests.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field

from offline.localization_package.cloud_manifest import CloudManifestError, decode_cloud_manifest_candidate
from offline.localization_package.package_schema import is_release_id, is_safe_id
from offline.localization_package.schema import (
    TYPE_DESCRIPTORS,
    TYPE_LANDMARKS,
    TYPE_S_WALL_COLMAP,
    ReasonCode as PackageReason,
)

from offline.publisher.keys import CATALOG_KEY, published_asset_key, published_manifest_key
from offline.publisher.store import ConcurrentModification, PromotionStore, PublisherStoreError

from .catalog import (
    CatalogError,
    decode_catalog,
    empty_catalog,
    encode_catalog,
    release_ordinal,
)
from .schema import PromotionState, ReasonCode, TERMINAL_SUCCESS

logger = logging.getLogger("offline.catalog_promotion")


@dataclass
class PromotionResult:
    state: str
    reason_code: str | None = None
    wall_id: str | None = None
    release_id: str | None = None
    name: str | None = None
    promotion_approved: bool = False
    remote_release_validated: bool = False
    catalog_discoverable: bool = False
    puts: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.state in {item.value for item in TERMINAL_SUCCESS}


def promote_localization_release(
    *,
    wall_id: str,
    release_id: str,
    name: str,
    approve: bool,
    store: PromotionStore | None,
) -> PromotionResult:
    base = PromotionResult(
        state=PromotionState.PROMOTION_NOT_AUTHORIZED.value,
        wall_id=wall_id,
        release_id=release_id,
        name=name,
        promotion_approved=False,
        catalog_discoverable=False,
    )
    if not approve:
        return _fail(base, PromotionState.PROMOTION_NOT_AUTHORIZED, ReasonCode.PROMOTION_NOT_AUTHORIZED)
    base.promotion_approved = True
    if not is_safe_id(wall_id):
        return _fail(base, PromotionState.REMOTE_RELEASE_INVALID, ReasonCode.INVALID_WALL_ID)
    if not is_release_id(release_id):
        return _fail(base, PromotionState.REMOTE_RELEASE_INVALID, ReasonCode.INVALID_RELEASE_ID)
    if not isinstance(name, str) or not name or name.strip() != name or not name.strip():
        return _fail(base, PromotionState.REMOTE_RELEASE_INVALID, ReasonCode.INVALID_DISPLAY_NAME)
    if store is None:
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.STORE_REQUIRED)

    try:
        _validate_remote_release(store, wall_id, release_id)
    except _PromotionFail as exc:
        return _fail(base, PromotionState.REMOTE_RELEASE_INVALID, exc.reason)
    except PublisherStoreError:
        logger.warning("catalog promotion remote release GET failed")
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)
    base.remote_release_validated = True

    try:
        current = store.get_conditional(CATALOG_KEY)
    except PublisherStoreError:
        logger.warning("catalog promotion catalog GET failed")
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)

    if current is None:
        catalog = empty_catalog()
        expected_etag: str | None = None
    else:
        if not current.etag:
            return _fail(base, PromotionState.CATALOG_INVALID, ReasonCode.CATALOG_ETAG_MISSING)
        expected_etag = current.etag
        try:
            payload = json.loads(current.data.decode("utf-8"))
            catalog = decode_catalog(payload)
        except json.JSONDecodeError:
            return _fail(base, PromotionState.CATALOG_INVALID, ReasonCode.CATALOG_INVALID)
        except UnicodeDecodeError:
            return _fail(base, PromotionState.CATALOG_INVALID, ReasonCode.CATALOG_INVALID)
        except CatalogError as exc:
            reason = (
                ReasonCode.CATALOG_SCHEMA_UNSUPPORTED
                if exc.code == "CATALOG_SCHEMA_UNSUPPORTED"
                else ReasonCode.CATALOG_INVALID
            )
            return _fail(base, PromotionState.CATALOG_INVALID, reason)

    try:
        candidate = _apply_promotion(catalog, wall_id=wall_id, name=name, release_id=release_id)
    except _PromotionFail as exc:
        state = {
            ReasonCode.CATALOG_NAME_CONFLICT: PromotionState.CATALOG_NAME_CONFLICT,
            ReasonCode.CATALOG_RELEASE_REGRESSION: PromotionState.CATALOG_RELEASE_REGRESSION,
            ReasonCode.CATALOG_INVALID: PromotionState.CATALOG_INVALID,
        }.get(exc.reason, PromotionState.CATALOG_INVALID)
        return _fail(base, state, exc.reason)

    if current is not None and candidate == catalog:
        base.state = PromotionState.ALREADY_CATALOG_DISCOVERABLE.value
        base.reason_code = None
        base.catalog_discoverable = True
        return base

    candidate_bytes = encode_catalog(candidate)

    try:
        store.put_if_match(CATALOG_KEY, candidate_bytes, expected_etag=expected_etag)
        base.puts.append(CATALOG_KEY)
    except ConcurrentModification:
        return _fail(base, PromotionState.CATALOG_CONCURRENT_MODIFICATION, ReasonCode.CATALOG_CONCURRENT_MODIFICATION)
    except PublisherStoreError:
        logger.warning("catalog promotion conditional PUT failed")
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)

    try:
        remote = store.get_bytes(CATALOG_KEY)
    except PublisherStoreError:
        logger.warning("catalog promotion post-write GET failed")
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)
    if remote is None or remote != candidate_bytes or _sha256(remote) != _sha256(candidate_bytes):
        return _fail(base, PromotionState.CATALOG_VERIFY_FAILED, ReasonCode.CATALOG_VERIFY_FAILED)
    try:
        verified = decode_catalog(json.loads(remote.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, CatalogError):
        return _fail(base, PromotionState.CATALOG_VERIFY_FAILED, ReasonCode.CATALOG_VERIFY_FAILED)
    if not _entry_matches(verified, wall_id=wall_id, name=name, release_id=release_id):
        return _fail(base, PromotionState.CATALOG_VERIFY_FAILED, ReasonCode.CATALOG_VERIFY_FAILED)
    if not _unrelated_preserved(catalog, verified, wall_id):
        return _fail(base, PromotionState.CATALOG_VERIFY_FAILED, ReasonCode.CATALOG_VERIFY_FAILED)

    base.state = PromotionState.CATALOG_DISCOVERABLE.value
    base.reason_code = None
    base.catalog_discoverable = True
    return base


class _PromotionFail(Exception):
    def __init__(self, reason: ReasonCode):
        super().__init__(reason.value)
        self.reason = reason


_MISSING_TYPE_REASON = {
    TYPE_DESCRIPTORS: ReasonCode.REMOTE_DESCRIPTORS_MISSING,
    TYPE_LANDMARKS: ReasonCode.REMOTE_LANDMARKS_MISSING,
    TYPE_S_WALL_COLMAP: ReasonCode.REMOTE_SIM3_MISSING,
}


def _missing_asset_reason(asset_type: str) -> ReasonCode:
    return _MISSING_TYPE_REASON.get(asset_type, ReasonCode.REMOTE_ASSET_MISSING)


def _manifest_reason(exc: CloudManifestError) -> ReasonCode:
    if exc.code == PackageReason.WALL_ID_MISMATCH:
        return ReasonCode.REMOTE_MANIFEST_WALL_ID_MISMATCH
    if exc.code == PackageReason.RELEASE_ID_MISMATCH:
        return ReasonCode.REMOTE_MANIFEST_RELEASE_ID_MISMATCH
    if exc.code == PackageReason.MISSING_REQUIRED_ASSET:
        message = str(exc)
        for asset_type, reason in _MISSING_TYPE_REASON.items():
            if asset_type in message:
                return reason
        return ReasonCode.REMOTE_ASSET_MISSING
    if exc.code == PackageReason.CLOUD_MANIFEST_INVALID:
        message = str(exc)
        if "duplicate semantic type" in message:
            return ReasonCode.REMOTE_DUPLICATE_SEMANTIC_TYPE
        if "required=true" in message:
            return ReasonCode.REMOTE_ASSET_NOT_REQUIRED
    return ReasonCode.REMOTE_MANIFEST_INVALID


def _validate_remote_release(store: PromotionStore, wall_id: str, release_id: str) -> None:
    raw = store.get_bytes(published_manifest_key(wall_id, release_id))
    if raw is None:
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_MISSING)
    try:
        payload = json.loads(raw.decode("utf-8"))
        manifest = decode_cloud_manifest_candidate(payload, wall_id=wall_id, release_id=release_id)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID) from None
    except CloudManifestError as exc:
        raise _PromotionFail(_manifest_reason(exc)) from None
    for item in manifest["assets"]:
        key = published_asset_key(wall_id, release_id, str(item["assetId"]))
        remote = store.get_bytes(key)
        if remote is None:
            raise _PromotionFail(_missing_asset_reason(str(item.get("type") or "")))
        if len(remote) != item["bytes"]:
            raise _PromotionFail(ReasonCode.REMOTE_ASSET_BYTES_MISMATCH)
        if _sha256(remote) != item["sha256"]:
            raise _PromotionFail(ReasonCode.REMOTE_ASSET_SHA_MISMATCH)


def _apply_promotion(catalog: dict, *, wall_id: str, name: str, release_id: str) -> dict:
    walls = [dict(item) for item in catalog["walls"]]
    matches = [item for item in walls if item.get("wallId") == wall_id]
    if len(matches) > 1:
        raise _PromotionFail(ReasonCode.CATALOG_INVALID)
    if not matches:
        walls.append({"wallId": wall_id, "name": name, "latestReleaseId": release_id})
        out = dict(catalog)
        out["schema"] = catalog["schema"]
        out["walls"] = walls
        return out
    entry = matches[0]
    existing_name = entry.get("name")
    if existing_name != name:
        raise _PromotionFail(ReasonCode.CATALOG_NAME_CONFLICT)
    existing_release = str(entry.get("latestReleaseId") or "")
    if release_ordinal(release_id) < release_ordinal(existing_release):
        raise _PromotionFail(ReasonCode.CATALOG_RELEASE_REGRESSION)
    entry["latestReleaseId"] = release_id
    out = dict(catalog)
    out["schema"] = catalog["schema"]
    out["walls"] = walls
    return out


def _entry_matches(catalog: dict, *, wall_id: str, name: str, release_id: str) -> bool:
    found = [item for item in catalog["walls"] if item.get("wallId") == wall_id]
    if len(found) != 1:
        return False
    return found[0].get("name") == name and found[0].get("latestReleaseId") == release_id


def _unrelated_preserved(before: dict, after: dict, wall_id: str) -> bool:
    before_others = [item for item in before["walls"] if item.get("wallId") != wall_id]
    after_others = [item for item in after["walls"] if item.get("wallId") != wall_id]
    return before_others == after_others


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fail(result: PromotionResult, state: PromotionState, reason: ReasonCode) -> PromotionResult:
    result.state = state.value
    result.reason_code = reason.value
    if reason.value not in result.reason_codes:
        result.reason_codes.append(reason.value)
    result.catalog_discoverable = False
    return result
