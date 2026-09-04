"""In-memory COS stand-in. No network. No credentials. No delete."""

from __future__ import annotations

from .store import PublisherStoreError


class FakeObjectStore:
    """Records GET/PUT. Refuses to mutate differing existing bytes. No list/delete."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.gets: list[str] = []
        self.puts: list[str] = []
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
        if key in self.corrupt_after_put:
            self.objects[key] = data + b"\x00"
            return
        self.objects[key] = data


def raise_store_error(message: str = "cos request failed") -> PublisherStoreError:
    return PublisherStoreError(message)
