"""Invocation log for tests. Phase 1 records only allowlisted work."""

from __future__ import annotations

INVOKED: list[str] = []


def reset() -> None:
    INVOKED.clear()


def record(name: str) -> None:
    INVOKED.append(name)


def invoked() -> list[str]:
    return list(INVOKED)
