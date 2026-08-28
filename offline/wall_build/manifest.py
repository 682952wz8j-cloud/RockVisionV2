"""Run input manifest and freeze verification. Never writes incoming."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from offline.ingestion.hashing import sha256_file
from offline.ingestion.scan import iter_files
from offline.ingestion.detect import classify_file

from .states import ReasonCode

SCHEMA_VERSION = "wallBuild.inputManifest.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def list_incoming_files(incoming: Path) -> list[Path]:
    if not incoming.is_dir():
        return []
    return iter_files(incoming)


def file_entry(incoming: Path, path: Path) -> dict:
    rel = path.relative_to(incoming).as_posix()
    detected_type, method, signature = classify_file(path)
    stat = path.stat()
    return {
        "relativePath": rel,
        "fileSize": stat.st_size,
        "classification": detected_type.value,
        "detectionMethod": method,
        "mimeOrSignature": signature,
        "checksum": sha256_file(path),
        "checksumAlgorithm": "SHA-256",
    }


def build_input_manifest(*, run_id: str, wall_id: str, incoming: Path, run_start_time: str) -> dict:
    files = [file_entry(incoming, path) for path in list_incoming_files(incoming)]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "wallId": wall_id,
        "runStartTime": run_start_time,
        "incomingRoot": str(incoming),
        "fileCount": len(files),
        "files": files,
    }


def verify_input_manifest(incoming: Path, manifest: dict) -> tuple[bool, list[dict]]:
    """Return (unchanged, discrepancies)."""
    recorded = {item["relativePath"]: item for item in manifest.get("files") or []}
    current_paths = {path.relative_to(incoming).as_posix(): path for path in list_incoming_files(incoming)}
    discrepancies: list[dict] = []

    for rel, item in recorded.items():
        path = current_paths.get(rel)
        if path is None:
            discrepancies.append(
                {
                    "relativePath": rel,
                    "reason": ReasonCode.INPUT_MUTATED_DURING_RUN.value,
                    "detail": "file missing at freeze recheck",
                }
            )
            continue
        size = path.stat().st_size
        checksum = sha256_file(path)
        if size != item.get("fileSize") or checksum != item.get("checksum"):
            discrepancies.append(
                {
                    "relativePath": rel,
                    "reason": ReasonCode.INPUT_MUTATED_DURING_RUN.value,
                    "recordedFileSize": item.get("fileSize"),
                    "currentFileSize": size,
                    "recordedChecksum": item.get("checksum"),
                    "currentChecksum": checksum,
                }
            )

    for rel in sorted(set(current_paths) - set(recorded)):
        discrepancies.append(
            {
                "relativePath": rel,
                "reason": ReasonCode.INPUT_MUTATED_DURING_RUN.value,
                "detail": "file added after input freeze",
            }
        )

    return not discrepancies, discrepancies
