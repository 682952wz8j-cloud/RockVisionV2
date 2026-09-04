"""In-memory COS stand-in. No network. No credentials. No delete."""

from __future__ import annotations

from .keys import CATALOG_KEY, PROMOTIONS_PREFIX
from .store import ObjectAlreadyExists, PublisherStoreError


class FakeObjectStore:
    """Records GET/PUT. Refuses to mutate differing existing bytes. No list/delete.

    Promotion records use put_if_absent (x-cos-forbid-overwrite equivalent).
    Immutable release objects still use put_bytes and never overwrite differing bytes.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.gets: list[str] = []
        self.puts: list[str] = []
        self.absent_puts: list[str] = []
        self.overwrite_attempts: list[str] = []
        self.get_errors: dict[str, Exception] = {}
        self.put_errors: dict[str, Exception] = {}
        self.corrupt_after_put: set[str] = set()

    def get_bytes(self, key: str) -> bytes | None:
        self.calls.append(("GET", key))
        self.gets.append(key)
        if key in self.get_errors:
            raise self.get_errors[key]
        return self.objects.get(key)

    def put_bytes(self, key: str, data: bytes) -> None:
        self.calls.append(("PUT", key))
        self.puts.append(key)
        if key in self.put_errors:
            raise self.put_errors[key]
        existing = self.objects.get(key)
        if existing is not None and existing != data:
            self.overwrite_attempts.append(key)
            return
        stored = data + b"\x00" if key in self.corrupt_after_put else data
        self.objects[key] = stored

    def put_if_absent(self, key: str, data: bytes) -> None:
        if key == CATALOG_KEY or key.endswith("/catalog.json"):
            raise PublisherStoreError("immutable create must not write catalog.json")
        if not key.startswith(PROMOTIONS_PREFIX):
            raise PublisherStoreError("put_if_absent is promotion-record-only")
        self.calls.append(("PUT_IF_ABSENT", key))
        self.absent_puts.append(key)
        if key in self.put_errors:
            raise self.put_errors[key]
        existing = self.objects.get(key)
        if existing is not None:
            self.overwrite_attempts.append(key)
            raise ObjectAlreadyExists("promotion record already exists")
        stored = data + b"\x00" if key in self.corrupt_after_put else data
        self.objects[key] = stored
        self.puts.append(key)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        """In-memory prefix scan for tests. Not a COS service listing call."""
        return sorted(key for key in self.objects if key.startswith(prefix))


def raise_store_error(message: str = "cos request failed") -> PublisherStoreError:
    return PublisherStoreError(message)
