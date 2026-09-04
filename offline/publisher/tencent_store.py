"""Tencent COS adapter for publisher CAM only.

Uses CRAGPAL_PUBLISHER_* credentials. Does not use TENCENT_* runtime
read identity. GET and PUT only. No bucket listing. No delete.

This adapter is unused by unit tests and unused in Phase C real writes.
"""

from __future__ import annotations

from .config import PublisherConfig
from .keys import assert_not_catalog_key
from .store import PublisherStoreError

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


class TencentPublisherStore:
    def __init__(self, *, client, bucket: str):
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_config(cls, config: PublisherConfig) -> "TencentPublisherStore":
        from qcloud_cos import CosConfig, CosS3Client

        client = CosS3Client(
            CosConfig(
                Region=config.region,
                SecretId=config.secret_id,
                SecretKey=config.secret_key,
            )
        )
        return cls(client=client, bucket=config.bucket)

    def get_bytes(self, key: str) -> bytes | None:
        assert_not_catalog_key(key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].get_raw_stream().read()
        except Exception as exc:
            mapped = _map_missing_or_error(exc)
            if mapped is None:
                return None
            raise mapped from exc

    def put_bytes(self, key: str, data: bytes) -> None:
        assert_not_catalog_key(key)
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        except Exception as exc:
            mapped = _map_missing_or_error(exc)
            if mapped is None:
                raise PublisherStoreError("cos put returned missing") from exc
            raise mapped from exc


def _map_missing_or_error(exc: Exception) -> PublisherStoreError | None:
    """None means the object is missing. Otherwise a fail-closed error."""
    try:
        from qcloud_cos.cos_exception import CosClientError, CosServiceError
    except ImportError:
        return PublisherStoreError("cos request failed")

    if isinstance(exc, CosServiceError):
        status = _cos_status(exc)
        code = _cos_error_code(exc)
        if code in _NOT_FOUND_CODES or (status == 404 and code not in _AUTH_CODES):
            return None
        return PublisherStoreError("cos service failed")
    if isinstance(exc, CosClientError):
        return PublisherStoreError("cos client failed")
    return PublisherStoreError("cos request failed")


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
