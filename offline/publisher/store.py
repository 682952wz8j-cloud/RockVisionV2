"""Publisher object-store protocol.

GET and PUT only. No bucket listing. No delete. No overwrite of differing bytes.
"""

from __future__ import annotations

from typing import Protocol


class PublisherStoreError(RuntimeError):
    """Fail-closed COS/store failure. Not an immutable-release conflict."""


class ObjectStore(Protocol):
    def get_bytes(self, key: str) -> bytes | None:
        """Return object bytes, or None if the key does not exist."""

    def put_bytes(self, key: str, data: bytes) -> None:
        """Write bytes for a key that the pipeline has already proven absent."""
