from __future__ import annotations

import hashlib
from pathlib import Path

# Exact OS folder-metadata basenames. Not a hidden-file glob: `.notes.txt` still counts.
OS_METADATA_BASENAMES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})


def is_os_metadata_noise(path: Path) -> bool:
    return path.name.lower() in OS_METADATA_BASENAMES


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not is_os_metadata_noise(p)):
        rel = path.relative_to(root).as_posix()
        hashes[rel] = sha256_file(path)
    return hashes
