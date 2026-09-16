"""Dedicated incoming/<wallId>/routes/ namespace.

This is not a generic 'ignore extra incoming files' rule.
Stage 2 capture identity and INPUT_FREEZE must not consume this tree.
Route inputs carry their own SHA-256 provenance/freeze.
"""

from __future__ import annotations

ROUTE_NAMESPACE_DIR = "routes"


def _posix(relative_path: str) -> str:
    return relative_path.replace("\\", "/").lstrip("/")


def is_route_namespace_relative(relative_path: str) -> bool:
    parts = _posix(relative_path).split("/")
    return bool(parts) and parts[0] == ROUTE_NAMESPACE_DIR


def is_authoritative_route_relative(relative_path: str) -> bool:
    """incoming/<wallId>/routes/*.dxf only. Nested paths are not authoritative."""
    parts = _posix(relative_path).split("/")
    return (
        len(parts) == 2
        and parts[0] == ROUTE_NAMESPACE_DIR
        and parts[1].lower().endswith(".dxf")
        and parts[1] not in {".", ".."}
    )
