from __future__ import annotations

import json
from pathlib import Path

from .types import MISSING, InventoryRecord, RawAssetType

_MAX_TILESET_BYTES = 20_000_000


def _walk_content_uris(payload: object) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, dict):
            uri = content.get("uri")
            if isinstance(uri, str) and uri:
                found.append(uri)
        for value in payload.values():
            found.extend(_walk_content_uris(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_walk_content_uris(item))
    return found


def _load_json(path: Path) -> dict | None:
    try:
        if path.stat().st_size > _MAX_TILESET_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _collect_from_tileset(incoming: Path, tileset_rel: str) -> dict:
    start = incoming / tileset_rel
    referenced_json: set[str] = set()
    referenced_b3dm: set[str] = set()
    queue = [tileset_rel]
    seen: set[str] = set()
    while queue:
        rel = queue.pop(0)
        if rel in seen:
            continue
        seen.add(rel)
        path = incoming / rel
        payload = _load_json(path)
        if payload is None:
            continue
        if path.name.lower() == "tileset.json" or rel != tileset_rel:
            referenced_json.add(rel)
        for uri in _walk_content_uris(payload):
            target = (path.parent / uri).resolve()
            try:
                target_rel = target.relative_to(incoming.resolve()).as_posix()
            except ValueError:
                continue
            if not (incoming / target_rel).is_file():
                continue
            suffix = Path(target_rel).suffix.lower()
            if suffix == ".b3dm":
                referenced_b3dm.add(target_rel)
            elif suffix == ".json":
                queue.append(target_rel)
    referenced_json.discard(tileset_rel)
    return {
        "referencedJson": sorted(referenced_json),
        "referencedB3dm": sorted(referenced_b3dm),
    }


def _root_metadata(incoming: Path, tileset_rel: str) -> dict:
    payload = _load_json(incoming / tileset_rel) or {}
    root = payload.get("root") if isinstance(payload.get("root"), dict) else {}
    asset = payload.get("asset") if isinstance(payload.get("asset"), dict) else {}
    bounding = root.get("boundingVolume") if isinstance(root, dict) else None
    transform = root.get("transform") if isinstance(root, dict) else None
    crs = MISSING
    extras = asset.get("extras") if isinstance(asset.get("extras"), dict) else {}
    for key in ("crs", "CRS", "epsg", "EPSG", "wkt", "WKT"):
        if extras.get(key):
            crs = extras[key]
            break
    return {
        "boundingVolume": bounding if bounding is not None else MISSING,
        "rootTransform": transform if transform is not None else MISSING,
        "crs": crs,
        "gltfUpAxis": asset.get("gltfUpAxis", MISSING),
        "tilesetVersion": asset.get("version", MISSING),
        "geometricError": payload.get("geometricError", MISSING),
    }


def discover_tileset_datasets(
    records: list[InventoryRecord],
    incoming: Path,
) -> list[dict]:
    tileset_files = [
        rec.relative_path
        for rec in records
        if rec.filename.lower() == "tileset.json"
    ]
    if not tileset_files:
        return []

    collected = {rel: _collect_from_tileset(incoming, rel) for rel in tileset_files}
    referenced_by_other: set[str] = set()
    for rel, data in collected.items():
        for other in tileset_files:
            if other != rel and other in data["referencedJson"]:
                referenced_by_other.add(other)

    roots = [rel for rel in tileset_files if rel not in referenced_by_other]
    datasets: list[dict] = []
    b3dm_to_dataset: dict[str, str] = {}
    for root in roots:
        refs = collected[root]
        b3dm_paths = refs["referencedB3dm"]
        sizes = []
        for rec in records:
            if rec.relative_path in b3dm_paths:
                sizes.append(rec.file_size)
                b3dm_to_dataset.setdefault(rec.relative_path, root)
        meta = _root_metadata(incoming, root)
        tile_uris = len(b3dm_paths) + len(refs["referencedJson"])
        datasets.append(
            {
                "kind": "3DTilesDataset",
                "tilesetPath": root,
                "tileCount": tile_uris,
                "b3dmCount": len(b3dm_paths),
                "totalSize": sum(sizes),
                "boundingVolume": meta["boundingVolume"],
                "rootTransform": meta["rootTransform"],
                "crs": meta["crs"],
                "gltfUpAxis": meta["gltfUpAxis"],
                "tilesetVersion": meta["tilesetVersion"],
                "geometricError": meta["geometricError"],
                "childTilesets": refs["referencedJson"],
            }
        )

    for rec in records:
        if rec.filename.lower() == "tileset.json":
            extra = rec.extra.setdefault("structuredData", {})
            extra["role"] = "cesiumTilesetManifest"
            extra["datasetPath"] = (
                rec.relative_path
                if rec.relative_path in roots
                else next((d["tilesetPath"] for d in datasets if rec.relative_path in d["childTilesets"]), MISSING)
            )
        if rec.extension == ".b3dm":
            model = rec.extra.setdefault("model3D", {})
            dataset = b3dm_to_dataset.get(rec.relative_path)
            if dataset:
                model["role"] = "3dTilesTile"
                model["tilesetPath"] = dataset
            else:
                model["role"] = "b3dmUnreferenced"
                model["tilesetPath"] = MISSING
    return datasets
