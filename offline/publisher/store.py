"""Publisher object-store protocol.

GET and PUT only. No bucket listing. No delete. No overwrite of differing bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PublisherStoreError(RuntimeError):
    """Fail-closed COS/store failure. Not an immutable-release conflict."""


class ConcurrentModification(PublisherStoreError):
    """Conditional write precondition failed. Remote object changed."""


@dataclass(frozen=True)
class ConditionalObject:
    data: bytes
    etag: str


class ObjectStore(Protocol):
    def get_bytes(self, key: str) -> bytes | None:
        """Return object bytes, or None if the key does not exist."""

    def put_bytes(self, key: str, data: bytes) -> None:
        """Write bytes for a key that the pipeline has already proven absent."""


class PromotionStore(Protocol):
    """GET any published object. Conditional PUT is catalog-only."""

    def get_bytes(self, key: str) -> bytes | None:
        """Return object bytes, or None if the key does not exist."""

    def get_conditional(self, key: str) -> ConditionalObject | None:
        """Return bytes plus opaque ETag, or None if missing."""

    def put_if_match(self, key: str, data: bytes, *, expected_etag: str | None) -> None:
        """Compare-and-swap. expected_etag None means the object must be absent."""
