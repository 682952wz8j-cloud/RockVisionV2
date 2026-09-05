"""Fail-closed development_test promotion.

Separate from production promotion qualification. This path always emits
environment=development_test. It cannot be switched to production.

LOCALIZATION_CAPABLE != PRODUCTION_QUALIFIED.

Development promotion:
- binds to an already-published immutable release
- does not publish assets
- does not write catalog.json
- does not require Cloud s_wall_colmap_json
- does not claim production qualification

Known development-test properties such as developmentFixtureOnly,
notAWallPackage, Cloud wallId vs embedded landmark wallId mismatch, and
absent Cloud Sim3 do not by themselves fail this path. They also do not
become production claims.

Do not call this from the production promoter.
"""

from __future__ import annotations

import json
import re

from offline.localization_package.package_schema import is_release_id, is_safe_id
from offline.localization_package.schema import (
    CLOUD_MANIFEST_SCHEMA,
    ENVIRONMENT_DEVELOPMENT_TEST,
    TYPE_DESCRIPTORS,
    TYPE_LANDMARKS,
)
from offline.publisher.keys import published_asset_key, published_manifest_key, published_promotion_key
from offline.publisher.store import ObjectAlreadyExists, PromotionStore, PublisherStoreError

from .pipeline import (
    PromotionResult,
    _PromotionFail,
    _assert_promotion_coherent,
    _existing_record_result,
    _fail,
    _missing_asset_reason,
    _sha256,
    _utc_now,
)
from .record import PromotionRecordError, decode_promotion_record, encode_promotion_record, promotion_identity, promotion_record
from .schema import PromotionState, ReasonCode

DEVELOPMENT_TEST_ENVIRONMENT = ENVIRONMENT_DEVELOPMENT_TEST
DEVELOPMENT_TEST_NOT_PRODUCTION_QUALIFIED = True
DEVELOPMENT_REQUIRED_ASSET_TYPES = (TYPE_DESCRIPTORS, TYPE_LANDMARKS)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def promote_development_test_release(
    *,
    wall_id: str,
    release_id: str,
    name: str,
    approve: bool,
    store: PromotionStore | None,
    promoted_at: str | None = None,
) -> PromotionResult:
    """Create an immutable development_test promotion record.

    environment is hardcoded. There is no caller environment argument.
    """
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
        manifest_sha = _validate_development_remote_release(store, wall_id, release_id)
    except _PromotionFail as exc:
        return _fail(base, PromotionState.REMOTE_RELEASE_INVALID, exc.reason)
    except PublisherStoreError:
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)
    base.remote_release_validated = True

    key = published_promotion_key(wall_id, release_id)
    try:
        existing = store.get_bytes(key)
    except PublisherStoreError:
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)

    candidate = promotion_record(
        wall_id=wall_id,
        release_id=release_id,
        name=name,
        promoted_at=promoted_at or _utc_now(),
        release_manifest_sha256=manifest_sha,
        environment=DEVELOPMENT_TEST_ENVIRONMENT,
    )
    if existing is not None:
        return _existing_record_result(base, existing, candidate)

    try:
        _assert_promotion_coherent(
            store, wall_id=wall_id, name=name, environment=DEVELOPMENT_TEST_ENVIRONMENT
        )
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
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)

    try:
        remote = store.get_bytes(key)
    except PublisherStoreError:
        return _fail(base, PromotionState.COS_ERROR, ReasonCode.COS_ERROR)
    if remote is None or remote != candidate_bytes or _sha256(remote) != _sha256(candidate_bytes):
        return _fail(base, PromotionState.PROMOTION_VERIFY_FAILED, ReasonCode.PROMOTION_VERIFY_FAILED)
    try:
        verified = decode_promotion_record(json.loads(remote.decode("utf-8")), wall_id=wall_id, release_id=release_id)
    except (UnicodeDecodeError, json.JSONDecodeError, PromotionRecordError):
        return _fail(base, PromotionState.PROMOTION_VERIFY_FAILED, ReasonCode.PROMOTION_VERIFY_FAILED)
    if promotion_identity(verified) != promotion_identity(candidate):
        return _fail(base, PromotionState.PROMOTION_VERIFY_FAILED, ReasonCode.PROMOTION_VERIFY_FAILED)
    if verified.get("environment") != DEVELOPMENT_TEST_ENVIRONMENT:
        return _fail(base, PromotionState.PROMOTION_VERIFY_FAILED, ReasonCode.PROMOTION_VERIFY_FAILED)

    base.state = PromotionState.PROMOTION_RECORD_CREATED.value
    base.reason_code = None
    base.promotion_record_created = True
    base.catalog_discoverable = False
    return base


def decode_development_cloud_manifest(payload: object, *, wall_id: str, release_id: str) -> dict:
    """Development_test remote-manifest contract.

    Requires descriptors + landmarks. Does not require Cloud Sim3.
    Does not parse landmark JSON for production flags.
    """
    if not isinstance(payload, dict):
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
    if payload.get("schema") != CLOUD_MANIFEST_SCHEMA:
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
    rec_wall = str(payload.get("wallId") or "")
    rec_release = str(payload.get("releaseId") or "")
    if not is_safe_id(rec_wall):
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
    if not is_release_id(rec_release):
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
    if rec_wall != wall_id:
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_WALL_ID_MISMATCH)
    if rec_release != release_id:
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_RELEASE_ID_MISMATCH)
    if not isinstance(payload.get("createdAt"), str) or not payload["createdAt"]:
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
    seen: set[str] = set()
    types: dict[str, dict] = {}
    for item in assets:
        if not isinstance(item, dict):
            raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
        asset_id = str(item.get("assetId") or "")
        if not is_safe_id(asset_id):
            raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
        if asset_id in seen:
            raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
        seen.add(asset_id)
        asset_type = item.get("type")
        if not isinstance(asset_type, str) or not asset_type:
            raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
        required = item.get("required")
        if not isinstance(required, bool):
            raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
        sha = item.get("sha256")
        if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
            raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
        bytes_value = item.get("bytes")
        if not isinstance(bytes_value, int) or isinstance(bytes_value, bool) or bytes_value < 0:
            raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID)
        if asset_type in types:
            raise _PromotionFail(ReasonCode.REMOTE_DUPLICATE_SEMANTIC_TYPE)
        types[asset_type] = item
    for required_type, missing_reason in (
        (TYPE_DESCRIPTORS, ReasonCode.REMOTE_DESCRIPTORS_MISSING),
        (TYPE_LANDMARKS, ReasonCode.REMOTE_LANDMARKS_MISSING),
    ):
        item = types.get(required_type)
        if item is None:
            raise _PromotionFail(missing_reason)
        if item.get("required") is not True:
            raise _PromotionFail(ReasonCode.REMOTE_ASSET_NOT_REQUIRED)
    return payload


def _validate_development_remote_release(store: PromotionStore, wall_id: str, release_id: str) -> str:
    raw = store.get_bytes(published_manifest_key(wall_id, release_id))
    if raw is None:
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_MISSING)
    try:
        payload = json.loads(raw.decode("utf-8"))
        manifest = decode_development_cloud_manifest(payload, wall_id=wall_id, release_id=release_id)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _PromotionFail(ReasonCode.REMOTE_MANIFEST_INVALID) from None
    for item in manifest["assets"]:
        key = published_asset_key(wall_id, release_id, str(item["assetId"]))
        required = item.get("required") is True
        remote = store.get_bytes(key)
        if remote is None:
            if required:
                raise _PromotionFail(_missing_asset_reason(str(item.get("type") or "")))
            continue
        if len(remote) != item["bytes"]:
            raise _PromotionFail(ReasonCode.REMOTE_ASSET_BYTES_MISMATCH)
        if _sha256(remote) != item["sha256"]:
            raise _PromotionFail(ReasonCode.REMOTE_ASSET_SHA_MISMATCH)
    return _sha256(raw)
