"""Tencent COS published-release store. Keys are backend-owned, never client-supplied."""

from __future__ import annotations

import json
import os

from .catalog_projection import merge_legacy_and_projected, project_promotions
from .contract import (
    ContractError,
    assert_manifest_identity,
    empty_catalog,
    parse_published_promotion_key,
    published_asset_key,
    published_catalog_key,
    published_manifest_key,
    published_promotions_prefix,
    require_asset_id,
    require_release_id,
    require_wall_id,
    validate_catalog,
)
from .promotion import decode_promotion_record
from .store import NotFound, StorageFailure, StorageUnavailable

REQUIRED_ENV = (
    "TENCENT_COS_REGION",
    "TENCENT_SECRET_ID",
    "TENCENT_SECRET_KEY",
    "TENCENT_COS_BUCKET",
)

_NOT_FOUND_CODES = frozenset({"NoSuchKey", "NoSuchResource", "NoSuchVersion"})
_AUTH_CODES = frozenset(
    {
        "AccessDenied",
        "InvalidAccessKeyId",
        "SignatureDoesNotMatch",
        "AccountProblem",
        "InvalidBucketName",
        "NoSuchBucket",
    }
)


class CosStore:
    def __init__(self, *, client, bucket: str):
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_env(cls) -> "CosStore":
        missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
        if missing:
            raise StorageUnavailable("missing COS environment variables")
        from qcloud_cos import CosConfig, CosS3Client

        config = CosConfig(
            Region=os.environ["TENCENT_COS_REGION"],
            SecretId=os.environ["TENCENT_SECRET_ID"],
            SecretKey=os.environ["TENCENT_SECRET_KEY"],
        )
        return cls(client=CosS3Client(config), bucket=os.environ["TENCENT_COS_BUCKET"])

    def _get_object_bytes(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].get_raw_stream().read()
        except Exception as exc:
            raise _map_cos_exception(exc, key) from exc

    def _get_json(self, key: str) -> dict:
        body = self._get_object_bytes(key)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("published document is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ContractError("published document must be an object")
        return payload

    def catalog(self) -> dict:
        legacy = self._read_legacy_catalog()
        records = self._read_promotion_records()
        return merge_legacy_and_projected(legacy, project_promotions(records))

    def latest_release_id(self, wall_id: str) -> str:
        require_wall_id(wall_id)
        for item in self.catalog()["walls"]:
            if item["wallId"] == wall_id:
                return item["latestReleaseId"]
        raise NotFound(f"unknown wallId {wall_id}")

    def manifest(self, wall_id: str) -> dict:
        require_wall_id(wall_id)
        return self.manifest_for_release(wall_id, self.latest_release_id(wall_id))

    def manifest_for_release(self, wall_id: str, release_id: str) -> dict:
        require_wall_id(wall_id)
        require_release_id(release_id)
        payload = self._get_json(published_manifest_key(wall_id, release_id))
        return assert_manifest_identity(payload, wall_id, release_id)

    def asset_bytes(self, wall_id: str, release_id: str, asset_id: str) -> bytes:
        require_wall_id(wall_id)
        require_release_id(release_id)
        require_asset_id(asset_id)
        manifest = self.manifest_for_release(wall_id, release_id)
        known = {item["assetId"] for item in manifest["assets"]}
        if asset_id not in known:
            raise NotFound(f"unknown assetId {asset_id}")
        return self._get_object_bytes(published_asset_key(wall_id, release_id, asset_id))

    def _read_legacy_catalog(self) -> dict:
        try:
            payload = self._get_json(published_catalog_key())
        except NotFound:
            return empty_catalog()
        return validate_catalog(payload)

    def _read_promotion_records(self) -> list[dict]:
        keys = self._list_promotion_keys()
        records: list[dict] = []
        for key in keys:
            wall_id, release_id = parse_published_promotion_key(key)
            try:
                payload = self._get_json(key)
            except NotFound as exc:
                raise ContractError("listed promotion record is missing") from exc
            records.append(decode_promotion_record(payload, wall_id=wall_id, release_id=release_id))
        return records

    def _list_promotion_keys(self) -> list[str]:
        prefix = published_promotions_prefix()
        keys: list[str] = []
        marker = ""
        while True:
            try:
                response = self._client.list_objects(
                    Bucket=self._bucket,
                    Prefix=prefix,
                    Marker=marker,
                    MaxKeys=1000,
                )
            except Exception as exc:
                raise _map_cos_exception(exc, prefix) from exc
            contents = response.get("Contents") or []
            if isinstance(contents, dict):
                contents = [contents]
            page_keys: list[str] = []
            for item in contents:
                if not isinstance(item, dict):
                    raise ContractError("promotion listing is malformed")
                key = item.get("Key")
                if not isinstance(key, str) or not key:
                    raise ContractError("promotion listing is malformed")
                if key.endswith("/"):
                    continue
                page_keys.append(key)
            keys.extend(page_keys)
            truncated = response.get("IsTruncated")
            if truncated in (True, "true", "True"):
                marker = response.get("NextMarker") or (page_keys[-1] if page_keys else "")
                if not marker:
                    raise StorageFailure("cos list truncated without marker")
                continue
            break
        return sorted(keys)


def _map_cos_exception(exc: Exception, key: str) -> Exception:
    from qcloud_cos.cos_exception import CosClientError, CosServiceError

    if isinstance(exc, CosServiceError):
        status = _cos_status(exc)
        code = _cos_error_code(exc)
        if code in _NOT_FOUND_CODES or (status == 404 and code not in _AUTH_CODES):
            return NotFound(key)
        if code in _AUTH_CODES or status in (401, 403):
            return StorageFailure("cos authorization failed")
        return StorageFailure("cos service failed")
    if isinstance(exc, CosClientError):
        return StorageFailure("cos client failed")
    return StorageFailure("cos request failed")


def _cos_status(exc) -> int:
    try:
        return int(exc.get_status_code())
    except (TypeError, ValueError, AttributeError):
        return 0


def _cos_error_code(exc) -> str:
    try:
        code = exc.get_error_code()
    except Exception:
        return ""
    return code if isinstance(code, str) else ""
