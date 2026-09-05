"""Published-asset store protocol. BUILD != PUBLISHED."""

from __future__ import annotations

from typing import Protocol


class NotFound(LookupError):
    """Unknown published wall, release, or asset."""


class StorageUnavailable(RuntimeError):
    """Store is not configured. HTTP 503."""


class StorageFailure(RuntimeError):
    """Store I/O, auth, or service failure. HTTP 502."""


class AssetStore(Protocol):
    def catalog(self) -> dict: ...

    def debug_catalog(self) -> dict: ...

    def latest_release_id(self, wall_id: str) -> str: ...

    def debug_latest_release_id(self, wall_id: str) -> str: ...

    def manifest(self, wall_id: str) -> dict: ...

    def debug_manifest(self, wall_id: str) -> dict: ...

    def manifest_for_release(self, wall_id: str, release_id: str) -> dict: ...

    def asset_bytes(self, wall_id: str, release_id: str, asset_id: str) -> bytes: ...
