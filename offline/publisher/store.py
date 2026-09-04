"""Publisher object-store protocol.

GET and PUT only. No bucket listing. No delete. No overwrite of differing bytes.
"""

from __future__ import annotations

from typing import Protocol


class PublisherStoreError(RuntimeError):
    """Fail-closed COS/store failure. Not an immutable-release conflict."""


class ObjectAlreadyExists(PublisherStoreError):
    """Immutable create was rejected because the key already exists."""


class ObjectStore(Protocol):
    def get_bytes(self, key: str) -> bytes | None:
        """Return object bytes, or None if the key does not exist."""

    def put_bytes(self, key: str, data: bytes) -> None:
        """Write bytes for a key that the pipeline has already proven absent."""


class PromotionStore(Protocol):
    """GET published objects. Immutable create is promotion-record-only."""

    def get_bytes(self, key: str) -> bytes | None:
        """Return object bytes, or None if the key does not exist."""

    def put_if_absent(self, key: str, data: bytes) -> None:
        """Create only if missing. Never overwrite. Real COS: x-cos-forbid-overwrite."""
