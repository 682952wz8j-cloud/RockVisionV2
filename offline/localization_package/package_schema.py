"""Decode and type-check Production Localization Package v1 package.json."""

from __future__ import annotations

import re

from .schema import (
    ENVIRONMENTS,
    PACKAGE_SCHEMA,
    ReasonCode,
    STATE_CONSTRUCTED,
    STATE_NOT_PACKAGE_READY,
    STATE_PACKAGE_READY,
    TYPE_DESCRIPTORS,
    TYPE_LANDMARKS,
    TYPE_S_WALL_COLMAP,
)

_RELEASE_ID = re.compile(r"^r[0-9]{6}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN = ("..", "/", "\\", ":", "@")


class PackageSchemaError(ValueError):
    def __init__(self, code: ReasonCode, message: str):
        super().__init__(message)
        self.code = code


def is_safe_id(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if any(token in value for token in _FORBIDDEN):
        return False
    return _SAFE_ID.fullmatch(value) is not None


def is_release_id(value: str) -> bool:
    return isinstance(value, str) and _RELEASE_ID.fullmatch(value) is not None


def require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, f"{field} must be 64 lowercase hex")
    return value


def require_nonneg_int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, f"{field} must be a non-negative integer")
    return value


def decode_package_json(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "package.json must be an object")
    if payload.get("schema") != PACKAGE_SCHEMA:
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "unknown package schema")
    wall_id = payload.get("wallId")
    if not is_safe_id(str(wall_id or "")):
        raise PackageSchemaError(ReasonCode.INVALID_WALL_ID, "invalid wallId")
    release_id = payload.get("releaseId")
    if not is_release_id(str(release_id or "")):
        raise PackageSchemaError(ReasonCode.INVALID_RELEASE_ID, "invalid releaseId")
    environment = payload.get("environment")
    if environment not in ENVIRONMENTS:
        raise PackageSchemaError(ReasonCode.INVALID_ENVIRONMENT, "invalid environment")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict):
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "capabilities must be an object")
    if not isinstance(capabilities.get("localizationReady"), bool):
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "capabilities.localizationReady must be boolean")
    if not isinstance(capabilities.get("routeArReady"), bool):
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "capabilities.routeArReady must be boolean")
    state = payload.get("packageState")
    if state not in {STATE_CONSTRUCTED, STATE_NOT_PACKAGE_READY, STATE_PACKAGE_READY}:
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "invalid packageState")
    source = payload.get("sourceBuild")
    if not isinstance(source, dict):
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "sourceBuild must be an object")
    if not isinstance(source.get("runId"), str) or not source["runId"]:
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "sourceBuild.runId is required")
    selection = source.get("selection")
    if not isinstance(selection, dict):
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "sourceBuild.selection is required")
    checksums = source.get("selectedSourceJpegSha256")
    if not isinstance(checksums, dict) or not checksums:
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "selectedSourceJpegSha256 is required")
    for rel, digest in checksums.items():
        if not isinstance(rel, str) or not rel:
            raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "selected JPEG path must be a string")
        require_sha256(digest, field=f"selectedSourceJpegSha256[{rel}]")
    pq = source.get("positioningQuality")
    if not isinstance(pq, dict) or "positioningQualityReasonCode" not in pq:
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "sourceBuild.positioningQuality is required")
    height = source.get("heightDatum")
    if not isinstance(height, dict) or "heightGateExecutionAllowed" not in height:
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "sourceBuild.heightDatum is required")
    identity = source.get("colmapSourceIdentity")
    if not isinstance(identity, dict) or not isinstance(identity.get("modelFingerprint"), str) or not identity["modelFingerprint"]:
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "sourceBuild.colmapSourceIdentity.modelFingerprint is required")
    metric = payload.get("metricTransform")
    _require_asset_identity(metric, expected_type=TYPE_S_WALL_COLMAP, name="metricTransform")
    if not isinstance(metric, dict):
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "metricTransform must be an object")
    if not isinstance(metric.get("status"), str) or not metric["status"]:
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "metricTransform.status is required")
    if not isinstance(metric.get("source"), str) or not metric["source"]:
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "metricTransform.source is required")
    stage3 = payload.get("stage3")
    if not isinstance(stage3, dict):
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "stage3 must be an object")
    _require_asset_identity(stage3.get("descriptors"), expected_type=TYPE_DESCRIPTORS, name="stage3.descriptors")
    _require_asset_identity(stage3.get("landmarks"), expected_type=TYPE_LANDMARKS, name="stage3.landmarks")
    freeze = stage3.get("freezeIdentity")
    if freeze is not None:
        if not isinstance(freeze, dict):
            raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "stage3.freezeIdentity must be an object")
        if freeze.get("wallBuildRunId") is not None and not isinstance(freeze.get("wallBuildRunId"), str):
            raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "stage3.freezeIdentity.wallBuildRunId must be a string")
        if freeze.get("colmapModelFingerprint") is not None and not isinstance(freeze.get("colmapModelFingerprint"), str):
            raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "stage3.freezeIdentity.colmapModelFingerprint must be a string")
    routes = payload.get("routes")
    if not isinstance(routes, dict):
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, "routes must be an object")
    if routes.get("present") is not False or routes.get("authorized") is not False:
        raise PackageSchemaError(ReasonCode.ROUTES_NOT_AUTHORIZED, "routes must be present=false authorized=false")
    return payload


def _require_asset_identity(item: object, *, expected_type: str, name: str) -> None:
    if not isinstance(item, dict):
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, f"{name} must be an object")
    if not is_safe_id(str(item.get("assetId") or "")):
        raise PackageSchemaError(ReasonCode.INVALID_PACKAGE_SCHEMA, f"{name}.assetId is invalid")
    if item.get("type") != expected_type:
        raise PackageSchemaError(ReasonCode.ASSET_TYPE_MISMATCH, f"{name}.type must be {expected_type}")
    require_sha256(item.get("sha256"), field=f"{name}.sha256")
    require_nonneg_int(item.get("bytes"), field=f"{name}.bytes")
