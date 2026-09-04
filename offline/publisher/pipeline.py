"""Fail-closed immutable localization-package publisher.

Assets first → remote verification → manifest last.
Never writes published/catalog.json. Never deletes. Never overwrites differing bytes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from offline.localization_package.cloud_manifest import CloudManifestError, decode_cloud_manifest_candidate
from offline.localization_package.layout import asset_path, cloud_manifest_path
from offline.localization_package.package_schema import is_release_id, is_safe_id
from offline.localization_package.schema import (
    ENVIRONMENT_DEVELOPMENT_TEST,
    ENVIRONMENT_PRODUCTION,
    STATE_PACKAGE_READY,
)
from offline.localization_package.validate import PackageValidationResult, validate_package_dir

from .keys import (
    CATALOG_KEY,
    PublisherKeyError,
    assert_not_catalog_key,
    published_asset_key,
    published_manifest_key,
    published_release_prefix,
)
from .schema import PublicationState, ReasonCode, TERMINAL_SUCCESS
from .store import ObjectStore, PublisherStoreError

logger = logging.getLogger("offline.publisher")


@dataclass
class PlannedObject:
    key: str
    data: bytes
    sha256: str
    nbytes: int
    asset_id: str | None = None
    kind: str = "asset"


@dataclass
class PublishResult:
    state: str
    reason_code: str | None = None
    wall_id: str | None = None
    release_id: str | None = None
    package_dir: str | None = None
    destination_prefix: str | None = None
    package_ready: bool = False
    localization_ready: bool = False
    route_ar_ready: bool = False
    publish_approved: bool = False
    catalog_discoverable: bool = False
    published_release: bool = False
    asset_count: int = 0
    validator_ran: bool = False
    phase: str | None = None
    puts: list[str] = field(default_factory=list)
    already_identical: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.state in {item.value for item in TERMINAL_SUCCESS}


@dataclass
class LocalPublishGate:
    result: PublishResult
    validation: PackageValidationResult | None = None
    planned_assets: list[PlannedObject] = field(default_factory=list)
    planned_manifest: PlannedObject | None = None

    @property
    def local_ok(self) -> bool:
        return self.planned_manifest is not None and self.result.publish_approved


def publish_localization_package(
    *,
    wall_id: str,
    release_id: str,
    package_dir: Path,
    approve: bool,
    store: ObjectStore | None,
) -> PublishResult:
    gate = evaluate_local_publish_gate(
        wall_id=wall_id,
        release_id=release_id,
        package_dir=package_dir,
        approve=approve,
    )
    if not gate.local_ok:
        return gate.result
    if store is None:
        return _with_state(gate.result, PublicationState.COS_ERROR, ReasonCode.STORE_REQUIRED)
    return execute_remote_publish(gate, store)


def evaluate_local_publish_gate(
    *,
    wall_id: str,
    release_id: str,
    package_dir: Path,
    approve: bool,
) -> LocalPublishGate:
    base = PublishResult(
        state=PublicationState.NOT_AUTHORIZED.value,
        wall_id=wall_id,
        release_id=release_id,
        package_dir=str(package_dir),
        publish_approved=False,
        catalog_discoverable=False,
    )
    if not approve:
        base.reason_code = ReasonCode.PUBLISH_NOT_AUTHORIZED.value
        base.reason_codes = [ReasonCode.PUBLISH_NOT_AUTHORIZED.value]
        return LocalPublishGate(result=base)

    base.publish_approved = True
    if not is_safe_id(wall_id):
        return LocalPublishGate(
            result=_with_state(base, PublicationState.LOCAL_PACKAGE_NOT_READY, ReasonCode.INVALID_WALL_ID)
        )
    if not is_release_id(release_id):
        return LocalPublishGate(
            result=_with_state(base, PublicationState.LOCAL_PACKAGE_NOT_READY, ReasonCode.INVALID_RELEASE_ID)
        )
    try:
        base.destination_prefix = published_release_prefix(wall_id, release_id)
    except PublisherKeyError:
        return LocalPublishGate(
            result=_with_state(base, PublicationState.LOCAL_PACKAGE_NOT_READY, ReasonCode.INVALID_WALL_ID)
        )

    if not package_dir.is_dir():
        return LocalPublishGate(
            result=_with_state(base, PublicationState.LOCAL_PACKAGE_NOT_READY, ReasonCode.PACKAGE_DIR_MISSING)
        )

    validation = validate_package_dir(package_dir)
    base.validator_ran = True
    base.package_ready = validation.package_state == STATE_PACKAGE_READY and validation.ok
    base.localization_ready = validation.localization_ready
    base.route_ar_ready = validation.route_ar_ready
    base.reason_codes = list(validation.reason_codes)

    if validation.wall_id is not None and validation.wall_id != wall_id:
        return LocalPublishGate(
            result=_with_state(base, PublicationState.LOCAL_PACKAGE_NOT_READY, ReasonCode.WALL_ID_MISMATCH),
            validation=validation,
        )
    if validation.release_id is not None and validation.release_id != release_id:
        return LocalPublishGate(
            result=_with_state(base, PublicationState.LOCAL_PACKAGE_NOT_READY, ReasonCode.RELEASE_ID_MISMATCH),
            validation=validation,
        )
    if validation.environment == ENVIRONMENT_DEVELOPMENT_TEST or validation.environment != ENVIRONMENT_PRODUCTION:
        return LocalPublishGate(
            result=_with_state(
                base,
                PublicationState.LOCAL_PACKAGE_NOT_READY,
                ReasonCode.DEVELOPMENT_PACKAGE_NOT_PUBLISHABLE,
            ),
            validation=validation,
        )
    if not validation.ok or validation.package_state != STATE_PACKAGE_READY or not validation.localization_ready:
        return LocalPublishGate(
            result=_with_state(base, PublicationState.LOCAL_PACKAGE_NOT_READY, ReasonCode.LOCAL_PACKAGE_NOT_READY),
            validation=validation,
        )

    try:
        planned_assets, planned_manifest = _plan_objects(package_dir, wall_id, release_id)
    except (OSError, json.JSONDecodeError, CloudManifestError, PublisherKeyError, ValueError):
        return LocalPublishGate(
            result=_with_state(base, PublicationState.LOCAL_PACKAGE_NOT_READY, ReasonCode.LOCAL_PACKAGE_NOT_READY),
            validation=validation,
        )
    base.asset_count = len(planned_assets)
    base.state = PublicationState.UPLOADING.value
    base.reason_code = None
    return LocalPublishGate(
        result=base,
        validation=validation,
        planned_assets=planned_assets,
        planned_manifest=planned_manifest,
    )


def execute_remote_publish(gate: LocalPublishGate, store: ObjectStore) -> PublishResult:
    result = gate.result
    planned_assets = gate.planned_assets
    planned_manifest = gate.planned_manifest
    if planned_manifest is None:
        return _with_state(result, PublicationState.LOCAL_PACKAGE_NOT_READY, ReasonCode.LOCAL_PACKAGE_NOT_READY)

    result.phase = PublicationState.PRECHECK_FAILED.value
    try:
        precheck = _precheck_release(store, planned_assets, planned_manifest)
    except PublisherStoreError:
        logger.warning("publisher COS precheck failed")
        return _with_state(result, PublicationState.COS_ERROR, ReasonCode.COS_ERROR)
    except PublisherKeyError:
        return _with_state(result, PublicationState.PRECHECK_FAILED, ReasonCode.CATALOG_KEY_FORBIDDEN)

    if precheck.conflict_key is not None:
        return _with_state(result, PublicationState.IMMUTABLE_RELEASE_CONFLICT, ReasonCode.IMMUTABLE_RELEASE_CONFLICT)
    if precheck.incomplete_published:
        return _with_state(result, PublicationState.PRECHECK_FAILED, ReasonCode.INCOMPLETE_PUBLISHED_RELEASE)

    result.already_identical = list(precheck.identical_keys)
    if precheck.all_identical:
        result.phase = PublicationState.VERIFYING.value
        try:
            if not _verify_release(store, planned_assets, planned_manifest, result.wall_id or "", result.release_id or ""):
                return _with_state(result, PublicationState.REMOTE_VERIFY_FAILED, ReasonCode.REMOTE_MANIFEST_VERIFY_FAILED)
        except PublisherStoreError:
            logger.warning("publisher COS verify failed")
            return _with_state(result, PublicationState.COS_ERROR, ReasonCode.COS_ERROR)
        result.state = PublicationState.ALREADY_PUBLISHED_IDENTICAL.value
        result.reason_code = None
        result.published_release = True
        result.catalog_discoverable = False
        result.phase = PublicationState.ALREADY_PUBLISHED_IDENTICAL.value
        return result

    result.phase = PublicationState.UPLOADING.value
    for item in planned_assets:
        if item.key in precheck.identical_keys:
            continue
        try:
            if not _safe_put_and_verify(store, item, puts=result.puts):
                return _with_state(result, PublicationState.REMOTE_VERIFY_FAILED, ReasonCode.REMOTE_ASSET_VERIFY_FAILED)
        except ImmutableConflict:
            return _with_state(result, PublicationState.IMMUTABLE_RELEASE_CONFLICT, ReasonCode.IMMUTABLE_RELEASE_CONFLICT)
        except PublisherStoreError:
            logger.warning("publisher COS upload failed")
            return _with_state(result, PublicationState.COS_ERROR, ReasonCode.COS_ERROR)

    result.phase = PublicationState.VERIFYING.value
    try:
        if not _verify_assets(store, planned_assets):
            return _with_state(result, PublicationState.REMOTE_VERIFY_FAILED, ReasonCode.REMOTE_ASSET_VERIFY_FAILED)
    except PublisherStoreError:
        logger.warning("publisher COS asset verify failed")
        return _with_state(result, PublicationState.COS_ERROR, ReasonCode.COS_ERROR)

    if planned_manifest.key not in precheck.identical_keys:
        try:
            if not _safe_put_and_verify(store, planned_manifest, puts=result.puts):
                return _with_state(
                    result,
                    PublicationState.REMOTE_VERIFY_FAILED,
                    ReasonCode.REMOTE_MANIFEST_VERIFY_FAILED,
                )
        except ImmutableConflict:
            return _with_state(result, PublicationState.IMMUTABLE_RELEASE_CONFLICT, ReasonCode.IMMUTABLE_RELEASE_CONFLICT)
        except PublisherStoreError:
            logger.warning("publisher COS manifest upload failed")
            return _with_state(result, PublicationState.COS_ERROR, ReasonCode.COS_ERROR)

    try:
        if not _verify_manifest(store, planned_manifest, result.wall_id or "", result.release_id or ""):
            return _with_state(
                result,
                PublicationState.REMOTE_VERIFY_FAILED,
                ReasonCode.REMOTE_MANIFEST_IDENTITY_MISMATCH,
            )
    except PublisherStoreError:
        logger.warning("publisher COS manifest verify failed")
        return _with_state(result, PublicationState.COS_ERROR, ReasonCode.COS_ERROR)

    result.state = PublicationState.PUBLISHED.value
    result.reason_code = None
    result.published_release = True
    result.catalog_discoverable = False
    result.phase = PublicationState.PUBLISHED.value
    return result


class ImmutableConflict(RuntimeError):
    pass


@dataclass
class _Precheck:
    identical_keys: list[str]
    conflict_key: str | None = None
    all_identical: bool = False
    incomplete_published: bool = False


def _plan_objects(package_dir: Path, wall_id: str, release_id: str) -> tuple[list[PlannedObject], PlannedObject]:
    manifest_path = cloud_manifest_path(package_dir)
    manifest_bytes = manifest_path.read_bytes()
    payload = json.loads(manifest_bytes.decode("utf-8"))
    decoded = decode_cloud_manifest_candidate(payload, wall_id=wall_id, release_id=release_id)
    planned: list[PlannedObject] = []
    for item in decoded["assets"]:
        asset_id = str(item["assetId"])
        data = asset_path(package_dir, asset_id).read_bytes()
        digest = _sha256(data)
        if digest != item["sha256"] or len(data) != item["bytes"]:
            raise ValueError("local asset does not match cloud-manifest declaration")
        key = published_asset_key(wall_id, release_id, asset_id)
        assert_not_catalog_key(key)
        planned.append(
            PlannedObject(
                key=key,
                data=data,
                sha256=digest,
                nbytes=len(data),
                asset_id=asset_id,
                kind="asset",
            )
        )
    manifest_key = published_manifest_key(wall_id, release_id)
    assert_not_catalog_key(manifest_key)
    return planned, PlannedObject(
        key=manifest_key,
        data=manifest_bytes,
        sha256=_sha256(manifest_bytes),
        nbytes=len(manifest_bytes),
        kind="manifest",
    )


def _precheck_release(
    store: ObjectStore,
    assets: list[PlannedObject],
    manifest: PlannedObject,
) -> _Precheck:
    identical: list[str] = []
    missing_assets = 0
    for item in [*assets, manifest]:
        assert_not_catalog_key(item.key)
        remote = store.get_bytes(item.key)
        if remote is None:
            if item.kind == "asset":
                missing_assets += 1
            continue
        if remote != item.data or _sha256(remote) != item.sha256 or len(remote) != item.nbytes:
            return _Precheck(identical_keys=identical, conflict_key=item.key)
        identical.append(item.key)

    manifest_present = manifest.key in identical
    if manifest_present and missing_assets:
        return _Precheck(identical_keys=identical, incomplete_published=True)
    all_identical = manifest_present and missing_assets == 0 and len(identical) == len(assets) + 1
    return _Precheck(identical_keys=identical, all_identical=all_identical)


def _safe_put_and_verify(store: ObjectStore, item: PlannedObject, *, puts: list[str]) -> bool:
    assert_not_catalog_key(item.key)
    current = store.get_bytes(item.key)
    if current is not None:
        if current == item.data and _matches_declaration(current, item):
            return True
        raise ImmutableConflict(item.key)
    store.put_bytes(item.key, item.data)
    puts.append(item.key)
    remote = store.get_bytes(item.key)
    if remote is None or remote != item.data or not _matches_declaration(remote, item):
        return False
    return True


def _verify_assets(store: ObjectStore, assets: list[PlannedObject]) -> bool:
    for item in assets:
        remote = store.get_bytes(item.key)
        if remote is None or remote != item.data or not _matches_declaration(remote, item):
            return False
    return True


def _verify_release(
    store: ObjectStore,
    assets: list[PlannedObject],
    manifest: PlannedObject,
    wall_id: str,
    release_id: str,
) -> bool:
    if not _verify_assets(store, assets):
        return False
    return _verify_manifest(store, manifest, wall_id, release_id)


def _verify_manifest(store: ObjectStore, item: PlannedObject, wall_id: str, release_id: str) -> bool:
    remote = store.get_bytes(item.key)
    if remote is None or remote != item.data or not _matches_declaration(remote, item):
        return False
    try:
        payload = json.loads(remote.decode("utf-8"))
        decode_cloud_manifest_candidate(payload, wall_id=wall_id, release_id=release_id)
    except (UnicodeDecodeError, json.JSONDecodeError, CloudManifestError):
        return False
    if payload.get("wallId") != wall_id or payload.get("releaseId") != release_id:
        return False
    return True


def _matches_declaration(data: bytes, item: PlannedObject) -> bool:
    return _sha256(data) == item.sha256 and len(data) == item.nbytes


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _with_state(result: PublishResult, state: PublicationState, reason: ReasonCode) -> PublishResult:
    result.state = state.value
    result.reason_code = reason.value
    if reason.value not in result.reason_codes:
        result.reason_codes.append(reason.value)
    result.published_release = False
    result.catalog_discoverable = False
    return result


def destination_keys(wall_id: str, release_id: str, asset_ids: list[str]) -> list[str]:
    keys = [published_asset_key(wall_id, release_id, asset_id) for asset_id in asset_ids]
    keys.append(published_manifest_key(wall_id, release_id))
    for key in keys:
        assert_not_catalog_key(key)
    if CATALOG_KEY in keys:
        raise PublisherKeyError("catalog key leaked into destination set")
    return keys
