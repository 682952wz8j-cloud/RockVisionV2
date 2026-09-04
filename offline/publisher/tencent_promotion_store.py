"""Tencent COS catalog promotion adapter.

GET any published object. Conditional PUT is catalog-only (If-Match /
If-None-Match). No delete. No bucket listing. No runtime TENCENT_* identity.
"""

from __future__ import annotations

from .config import PublisherConfig
from .keys import CATALOG_KEY
from .store import ConcurrentModification, ConditionalObject, PublisherStoreError
from .tencent_store import _map_missing_or_error, _cos_error_code, _cos_status


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

    def get_conditional(self, key: str) -> ConditionalObject | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            data = response["Body"].get_raw_stream().read()
        except Exception as exc:
            mapped = _map_missing_or_error(exc)
            if mapped is None:
                return None
            raise mapped from exc
        etag = response.get("ETag")
        if not isinstance(etag, str) or not etag:
            raise PublisherStoreError("catalog response missing ETag")
        return ConditionalObject(data=data, etag=etag)

    def put_if_match(self, key: str, data: bytes, *, expected_etag: str | None) -> None:
        if key != CATALOG_KEY:
            raise PublisherStoreError("conditional put is catalog-only")
        kwargs = {"Bucket": self._bucket, "Key": key, "Body": data}
        if expected_etag is None:
            kwargs["IfNoneMatch"] = "*"
        else:
            kwargs["IfMatch"] = expected_etag
        try:
            self._client.put_object(**kwargs)
        except Exception as exc:
            if _is_precondition_failed(exc):
                raise ConcurrentModification("catalog precondition failed") from exc
            mapped = _map_missing_or_error(exc)
            if mapped is None:
                raise PublisherStoreError("cos put returned missing") from exc
            raise mapped from exc


def _is_precondition_failed(exc: Exception) -> bool:
    status = _cos_status(exc)
    code = _cos_error_code(exc)
    if status == 412:
        return True
    return code in {"PreconditionFailed", "FileAlreadyExists"}
