"""Tencent COS immutable promotion-record adapter.

GET published objects. Create-only PUT for promotion records using
x-cos-forbid-overwrite=true. No ETag precondition headers. No catalog
write. No delete. No prefix listing. No runtime TENCENT_* identity.

Phase D0.5 proved Tencent PUT ETag preconditions are not a safe
lost-update primitive. This adapter does not use them.
"""

from __future__ import annotations

from .config import PublisherConfig
from .keys import CATALOG_KEY, PROMOTIONS_PREFIX
from .store import ObjectAlreadyExists, PublisherStoreError
from .tencent_store import _map_missing_or_error, _cos_error_code, _cos_status

_FORBID_OVERWRITE_PARAM = "ForbidOverwrite"
_FORBID_OVERWRITE_HEADER = "x-cos-forbid-overwrite"
_ALREADY_EXISTS_CODES = frozenset(
    {
        "FileAlreadyExists",
        "ObjectAlreadyExists",
        "Conflict",
        "ForbidOverwrite",
    }
)


class TencentPromotionStore:
    def __init__(self, *, client, bucket: str):
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_config(cls, config: PublisherConfig) -> "TencentPromotionStore":
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
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].get_raw_stream().read()
        except Exception as exc:
            mapped = _map_missing_or_error(exc)
            if mapped is None:
                return None
            raise mapped from exc

    def put_if_absent(self, key: str, data: bytes) -> None:
        if key == CATALOG_KEY or key.endswith("/catalog.json"):
            raise PublisherStoreError("promotion store must not write catalog.json")
        if not key.startswith(PROMOTIONS_PREFIX):
            raise PublisherStoreError("put_if_absent is promotion-record-only")
        _ensure_forbid_overwrite_mapping()
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ForbidOverwrite="true",
            )
        except Exception as exc:
            if _is_already_exists(exc):
                raise ObjectAlreadyExists("promotion record already exists") from exc
            mapped = _map_missing_or_error(exc)
            if mapped is None:
                raise PublisherStoreError("cos put returned missing") from exc
            raise mapped from exc


def _ensure_forbid_overwrite_mapping() -> None:
    """cos-python-sdk-v5 maplist omits the documented forbid-overwrite header.

    Register the mapping so the signed put_object path sends
    x-cos-forbid-overwrite: true. This is not an ETag precondition.
    """
    try:
        from qcloud_cos import cos_comm
    except ImportError:
        return
    if _FORBID_OVERWRITE_PARAM not in cos_comm.maplist:
        cos_comm.maplist[_FORBID_OVERWRITE_PARAM] = _FORBID_OVERWRITE_HEADER


def _is_already_exists(exc: Exception) -> bool:
    status = _cos_status(exc)
    code = _cos_error_code(exc)
    if status == 409:
        return True
    return code in _ALREADY_EXISTS_CODES
