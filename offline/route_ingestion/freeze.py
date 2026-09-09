"""Independent SHA-256 freeze of authoritative route DXF inputs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from offline.ingestion.hashing import sha256_file
from offline.ingestion.route_namespace import is_authoritative_route_relative

from .schema import FREEZE_SCHEMA, REASON_INPUT_MUTATED, REASON_PROVENANCE


class RouteFreezeError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_route_input_freeze(
    *,
    wall_id: str,
    incoming: Path,
    dxf_files: list[dict],
    frozen_at: str | None = None,
) -> dict:
    files = []
    for item in dxf_files:
        rel = item["relativePath"]
        if not is_authoritative_route_relative(rel):
            raise RouteFreezeError(REASON_PROVENANCE, f"not an authoritative route path: {rel}")
        path = incoming / rel
        if not path.is_file():
            raise RouteFreezeError(REASON_INPUT_MUTATED, f"missing route DXF {rel}")
        checksum = sha256_file(path)
        if checksum != item.get("sha256"):
            raise RouteFreezeError(REASON_PROVENANCE, f"discovery checksum mismatch for {rel}")
        files.append(
            {
                "relativePath": rel,
                "sourceFilename": item.get("sourceFilename") or path.name,
                "fileSize": path.stat().st_size,
                "sha256": checksum,
                "checksumAlgorithm": "SHA-256",
            }
        )
    digest_src = "|".join(f"{item['relativePath']}:{item['sha256']}" for item in files)
    import hashlib

    return {
        "schemaVersion": FREEZE_SCHEMA,
        "kind": "authoritative_route_input_freeze",
        "wallId": wall_id,
        "frozenAt": frozen_at or utc_now(),
        "fileCount": len(files),
        "files": files,
        "freezeSha256": hashlib.sha256(digest_src.encode("utf-8")).hexdigest(),
        "notAStage2InputFreeze": True,
        "notAProductionRoutePackage": True,
    }


def verify_route_input_freeze(incoming: Path, freeze: dict) -> None:
    recorded = {item["relativePath"]: item for item in freeze.get("files") or []}
    for rel, item in recorded.items():
        path = incoming / rel
        if not path.is_file():
            raise RouteFreezeError(REASON_INPUT_MUTATED, f"route DXF missing at recheck: {rel}")
        size = path.stat().st_size
        checksum = sha256_file(path)
        if size != item.get("fileSize") or checksum != item.get("sha256"):
            raise RouteFreezeError(REASON_INPUT_MUTATED, f"route DXF changed: {rel}")
