"""In-memory COS stand-in. No network. No credentials. No delete."""

from __future__ import annotations

import hashlib

from .keys import CATALOG_KEY
from .store import ConcurrentModification, ConditionalObject, PublisherStoreError


class FakeObjectStore:
    """Records GET/PUT. Refuses to mutate differing existing bytes. No list/delete.

    Catalog promotion uses put_if_match (ETag compare-and-swap). Immutable
    release objects still use put_bytes and never overwrite differing bytes.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.gets: list[str] = []
        self.puts: list[str] = []
        self.conditional_puts: list[str] = []
        self.overwrite_attempts: list[str] = []
        self.get_errors: dict[str, Exception] = {}
        self.put_errors: dict[str, Exception] = {}
        self.corrupt_after_put: set[str] = set()
        self.precondition_failures: set[str] = set()

    def get_bytes(self, key: str) -> bytes | None:
        self.calls.append(("GET", key))
        self.gets.append(key)
        if key in self.get_errors:
            raise self.get_errors[key]
        return self.objects.get(key)

    def get_conditional(self, key: str) -> ConditionalObject | None:
        data = self.get_bytes(key)
        if data is None:
            return None
        etag = self.etags.get(key) or self._etag_for(data)
        self.etags[key] = etag
        return ConditionalObject(data=data, etag=etag)

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
        self.etags[key] = self._etag_for(stored)

    def put_if_match(self, key: str, data: bytes, *, expected_etag: str | None) -> None:
        if key != CATALOG_KEY:
            raise PublisherStoreError("conditional put is catalog-only")
        self.calls.append(("PUT_IF_MATCH", key))
        self.conditional_puts.append(key)
        self.puts.append(key)
        if key in self.put_errors:
            raise self.put_errors[key]
        if key in self.precondition_failures:
            raise ConcurrentModification("precondition failed")
        existing = self.objects.get(key)
        current_etag = self.etags.get(key)
        if expected_etag is None:
            if existing is not None:
                raise ConcurrentModification("catalog already exists")
        else:
            if existing is None or current_etag != expected_etag:
                raise ConcurrentModification("catalog etag mismatch")
        stored = data + b"\x00" if key in self.corrupt_after_put else data
        self.objects[key] = stored
        self.etags[key] = self._etag_for(stored)

    def mutate(self, key: str, data: bytes) -> None:
        """Out-of-band concurrent writer for tests. Not a publisher API."""
        self.objects[key] = data
        self.etags[key] = self._etag_for(data)

    @staticmethod
    def _etag_for(data: bytes) -> str:
        return '"' + hashlib.md5(data).hexdigest() + '"'


def raise_store_error(message: str = "cos request failed") -> PublisherStoreError:
    return PublisherStoreError(message)
