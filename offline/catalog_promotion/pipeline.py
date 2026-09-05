"""Fail-closed immutable promotion records.

Validates an already-published immutable release, then creates
published/promotions/<wallId>/<releaseId>.json with forbid-overwrite.
Never rewrites assets, manifests, or published/catalog.json.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from offline.localization_package.cloud_manifest import CloudManifestError, decode_cloud_manifest_candidate
from offline.localization_package.package_schema import is_release_id, is_safe_id
from offline.localization_package.schema import (
    ENVIRONMENT_PRODUCTION,
    TYPE_DESCRIPTORS,
    TYPE_LANDMARKS,
    TYPE_S_WALL_COLMAP,
    ReasonCode as PackageReason,
)

from offline.publisher.keys import PROMOTIONS_PREFIX, published_asset_key, published_manifest_key, published_promotion_key
from offline.publisher.store import ObjectAlreadyExists, PromotionStore, PublisherStoreError

from .record import (
    PromotionRecordError,
    decode_promotion_record,
    encode_promotion_record,
    promotion_identity,
    promotion_record,
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
    promotion_record_created: bool = False
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
    promoted_at: str | None = None,
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
        manifest_sha = _validate_remote_release(store, wall_id, release_id)
    except _PromotionFail as exc:
        return _fail(base, PromotionState.REMOTE_RELEASE_INVALID, exc.reason)
    except PublisherStoreError:
        logger.warning("promotion remote release GET failed")
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)
    base.remote_release_validated = True

    key = published_promotion_key(wall_id, release_id)
    try:
        existing = store.get_bytes(key)
    except PublisherStoreError:
        logger.warning("promotion record GET failed")
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)

    candidate = promotion_record(
        wall_id=wall_id,
        release_id=release_id,
        name=name,
        promoted_at=promoted_at or _utc_now(),
        release_manifest_sha256=manifest_sha,
        environment=ENVIRONMENT_PRODUCTION,
    )
    if existing is not None:
        return _existing_record_result(base, existing, candidate)

    try:
        _assert_promotion_coherent(store, wall_id=wall_id, name=name, environment=ENVIRONMENT_PRODUCTION)
    except _PromotionFail as exc:
        if exc.reason == ReasonCode.PROMOTION_ENVIRONMENT_CONFLICT:
            return _fail(base, PromotionState.PROMOTION_ENVIRONMENT_CONFLICT, exc.reason)
        return _fail(base, PromotionState.PROMOTION_NAME_CONFLICT, exc.reason)

    candidate_bytes = encode_promotion_record(candidate)
    try:
        store.put_if_absent(key, candidate_bytes)
        base.puts.append(key)
    except ObjectAlreadyExists:
        try:
            raced = store.get_bytes(key)
        except PublisherStoreError:
            return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)
        if raced is None:
            return _fail(base, PromotionState.IMMUTABLE_PROMOTION_CONFLICT, ReasonCode.IMMUTABLE_PROMOTION_CONFLICT)
        return _existing_record_result(base, raced, candidate)
    except PublisherStoreError:
        logger.warning("promotion immutable create failed")
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)

    try:
        remote = store.get_bytes(key)
    except PublisherStoreError:
        logger.warning("promotion post-write GET failed")
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)
    if remote is None or remote != candidate_bytes or _sha256(remote) != _sha256(candidate_bytes):
        return _fail(base, PromotionState.PROMOTION_VERIFY_FAILED, ReasonCode.PROMOTION_VERIFY_FAILED)
    try:
        verified = decode_promotion_record(json.loads(remote.decode("utf-8")), wall_id=wall_id, release_id=release_id)
    except (UnicodeDecodeError, json.JSONDecodeError, PromotionRecordError):
        return _fail(base, PromotionState.PROMOTION_VERIFY_FAILED, ReasonCode.PROMOTION_VERIFY_FAILED)
    if promotion_identity(verified) != promotion_identity(candidate):
        return _fail(base, PromotionState.PROMOTION_VERIFY_FAILED, ReasonCode.PROMOTION_VERIFY_FAILED)

    base.state = PromotionState.PROMOTION_RECORD_CREATED.value
    base.reason_code = None
    base.promotion_record_created = True
    base.catalog_discoverable = False
    return base


def _existing_record_result(base: PromotionResult, existing: bytes, candidate: dict) -> PromotionResult:
    try:
        payload = json.loads(existing.decode("utf-8"))
        record = decode_promotion_record(payload, wall_id=base.wall_id, release_id=base.release_id)
    except (UnicodeDecodeError, json.JSONDecodeError, PromotionRecordError) as exc:
        reason = ReasonCode.PROMOTION_RECORD_INVALID
        if isinstance(exc, PromotionRecordError) and exc.code == "PROMOTION_SCHEMA_UNSUPPORTED":
            reason = ReasonCode.PROMOTION_SCHEMA_UNSUPPORTED
        elif isinstance(exc, PromotionRecordError) and exc.code == "PROMOTION_IDENTITY_CONFLICT":
            reason = ReasonCode.PROMOTION_IDENTITY_CONFLICT
        elif isinstance(exc, PromotionRecordError) and exc.code == "PROMOTION_ENVIRONMENT_INVALID":
            reason = ReasonCode.PROMOTION_ENVIRONMENT_INVALID
        return _fail(base, PromotionState.IMMUTABLE_PROMOTION_CONFLICT, reason)
    if promotion_identity(record) == promotion_identity(candidate):
        base.state = PromotionState.ALREADY_PROMOTED_IDENTICAL.value
        base.reason_code = None
        base.promotion_record_created = True
        base.catalog_discoverable = False
        return base
    return _fail(base, PromotionState.IMMUTABLE_PROMOTION_CONFLICT, ReasonCode.IMMUTABLE_PROMOTION_CONFLICT)


def _assert_promotion_coherent(
    store: PromotionStore, *, wall_id: str, name: str, environment: str
) -> None:
    keys_fn = getattr(store, "keys_with_prefix", None)
    if keys_fn is None:
        return
    prefix = f"{PROMOTIONS_PREFIX}{wall_id}/"
    names: set[str] = set()
    environments: set[str | None] = set()
    for key in keys_fn(prefix):
        raw = store.get_bytes(key)
        if raw is None:
            continue
        try:
            record = decode_promotion_record(json.loads(raw.decode("utf-8")), wall_id=wall_id)
        except (UnicodeDecodeError, json.JSONDecodeError, PromotionRecordError) as exc:
            if isinstance(exc, PromotionRecordError) and exc.code == "PROMOTION_SCHEMA_UNSUPPORTED":
                raise _PromotionFail(ReasonCode.PROMOTION_SCHEMA_UNSUPPORTED) from exc
            if isinstance(exc, PromotionRecordError) and exc.code == "PROMOTION_ENVIRONMENT_INVALID":
                raise _PromotionFail(ReasonCode.PROMOTION_ENVIRONMENT_INVALID) from exc
            raise _PromotionFail(ReasonCode.PROMOTION_RECORD_INVALID) from exc
        names.add(str(record["name"]))
        environments.add(record["environment"] if "environment" in record else None)
    if names and (len(names) > 1 or name not in names):
        raise _PromotionFail(ReasonCode.PROMOTION_NAME_CONFLICT)
    if environments and (len(environments) > 1 or environment not in environments):
        raise _PromotionFail(ReasonCode.PROMOTION_ENVIRONMENT_CONFLICT)


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


def _validate_remote_release(store: PromotionStore, wall_id: str, release_id: str) -> str:
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
    return _sha256(raw)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fail(result: PromotionResult, state: PromotionState, reason: ReasonCode) -> PromotionResult:
    result.state = state.value
    result.reason_code = reason.value
    if reason.value not in result.reason_codes:
        result.reason_codes.append(reason.value)
    result.catalog_discoverable = False
    result.promotion_record_created = False
    return result
