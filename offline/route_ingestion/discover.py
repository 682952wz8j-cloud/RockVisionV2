"""Discover incoming/<wallId>/routes/*.dxf. Do not require per-file CLI paths."""

from __future__ import annotations

from pathlib import Path

from offline.ingestion.hashing import is_os_metadata_noise, sha256_file
from offline.ingestion.pipeline import incoming_dir
from offline.ingestion.route_namespace import (
    ROUTE_NAMESPACE_DIR,
    is_authoritative_route_relative,
    is_route_namespace_relative,
)

from .schema import REASON_NO_ROUTES, REASON_UNEXPECTED_NAMESPACE


class RouteDiscoveryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def discover_route_dxf(root: Path, wall_id: str) -> dict:
    incoming = incoming_dir(root, wall_id)
    routes_dir = incoming / ROUTE_NAMESPACE_DIR
    if not routes_dir.is_dir():
        raise RouteDiscoveryError(REASON_NO_ROUTES, f"missing {ROUTE_NAMESPACE_DIR}/ under {wall_id}")

    unexpected: list[str] = []
    dxf: list[dict] = []
    for path in sorted(routes_dir.rglob("*")):
        if not path.is_file() or is_os_metadata_noise(path):
            continue
        rel = path.relative_to(incoming).as_posix()
        if is_authoritative_route_relative(rel):
            dxf.append(
                {
                    "relativePath": rel,
                    "sourceFilename": path.name,
                    "path": str(path),
                    "fileSize": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
            continue
        if is_route_namespace_relative(rel):
            unexpected.append(rel)

    if unexpected:
        raise RouteDiscoveryError(
            REASON_UNEXPECTED_NAMESPACE,
            "routes/ contains files that are not top-level *.dxf: " + ", ".join(unexpected),
        )
    if not dxf:
        raise RouteDiscoveryError(REASON_NO_ROUTES, f"no *.dxf in {ROUTE_NAMESPACE_DIR}/")
    return {
        "wallId": wall_id,
        "incomingRoot": str(incoming),
        "routesDirectory": str(routes_dir),
        "dxfFiles": dxf,
    }
