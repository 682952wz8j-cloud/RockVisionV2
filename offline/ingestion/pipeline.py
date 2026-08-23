from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .geospatial import associate_sidecars
from .report import render_validation_report
from .scan import build_record, find_duplicates, image_info
from .source_trees import (
    discover_source_trees,
    iter_tree_files,
    snapshot_source_trees,
    source_tree_public,
)
from .tilesets import discover_tileset_datasets
from .types import (
    MISSING,
    IngestionSummary,
    InventoryRecord,
    RawAssetType,
    RunResult,
)
from .validate import collect_warnings, decide_result, has_gps, is_readable_image

SCHEMA_VERSION = "1A.2"


def repo_root_from(start: Path) -> Path:
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / "incoming").is_dir() and (candidate / "offline").is_dir():
            return candidate
    raise FileNotFoundError("cannot locate repository root (incoming/ and offline/ required)")


def incoming_dir(root: Path, wall_id: str) -> Path:
    return root / "incoming" / wall_id


def output_dir(root: Path, wall_id: str) -> Path:
    return root / "offline" / "work" / wall_id / "ingestion"


def _extra_files(groups: list[list[str]]) -> int:
    return sum(len(group) - 1 for group in groups)


def build_summary(
    wall_id: str,
    incoming_root: Path,
    records: list[InventoryRecord],
    result: RunResult,
    warnings: list[str],
    errors: list[str],
    duplicates,
    datasets: list[dict],
    source_trees: list[dict] | None = None,
    previous_inventory_files: int | None = None,
) -> IngestionSummary:
    by_type = Counter(rec.detected_type.value for rec in records)
    images = [rec for rec in records if rec.detected_type == RawAssetType.IMAGE]
    readable = [rec for rec in images if is_readable_image(rec)]
    with_exif = 0
    with_gps = 0
    cameras: set[str] = set()
    for rec in readable:
        info = image_info(rec)
        if info is None:
            continue
        if info.has_exif is True:
            with_exif += 1
        if has_gps(info):
            with_gps += 1
        if info.camera_model != MISSING:
            cameras.add(info.camera_model)

    models = [rec for rec in records if rec.detected_type == RawAssetType.MODEL_3D]
    standalone = [rec for rec in models if rec.extension != ".b3dm"]
    b3dm = [rec for rec in records if rec.extension == ".b3dm"]
    b3dm_in = [rec for rec in b3dm if rec.extra.get("model3D", {}).get("tilesetPath") not in {None, MISSING}]
    routes = [rec for rec in records if rec.detected_type == RawAssetType.ROUTE_GEOMETRY]
    rtk = [rec for rec in records if rec.detected_type == RawAssetType.RTK_GNSS]
    tileset_json = [rec for rec in records if rec.filename.lower() == "tileset.json"]

    return IngestionSummary(
        wall_id=wall_id,
        incoming_root=str(incoming_root),
        total_files=len(records),
        by_type=dict(sorted(by_type.items())),
        images_detected=len(images),
        images_readable=len(readable),
        images_with_exif=with_exif,
        images_with_gps=with_gps,
        camera_models=sorted(cameras),
        rtk_candidates=len(rtk),
        rtk_parsed=0,
        rtk_parser_not_implemented=len(rtk),
        rtk_types=sorted({rec.extension.lstrip(".") or "unknown" for rec in rtk}),
        standalone_models=len(standalone),
        standalone_model_formats=sorted({rec.extension.lstrip(".") or "unknown" for rec in standalone}),
        geospatial_sidecars=by_type.get(RawAssetType.GEOSPATIAL_SIDECAR.value, 0),
        tileset_json_found=bool(tileset_json),
        tileset_json_count=len(tileset_json),
        tileset_datasets=len(datasets),
        b3dm_tiles=len(b3dm),
        b3dm_in_datasets=len(b3dm_in),
        b3dm_unreferenced=len(b3dm) - len(b3dm_in),
        route_geometry_detected=len(routes),
        route_formats=sorted({rec.extension.lstrip(".") or "unknown" for rec in routes}),
        structured_data=by_type.get(RawAssetType.STRUCTURED_DATA.value, 0),
        metadata=by_type.get(RawAssetType.METADATA.value, 0),
        unknown=by_type.get(RawAssetType.UNKNOWN.value, 0),
        exact_duplicate_groups=len(duplicates.exact_duplicates),
        exact_duplicate_files=_extra_files(duplicates.exact_duplicates),
        nonzero_duplicate_groups=len(duplicates.content_duplicates_nonzero),
        nonzero_duplicate_files=_extra_files(duplicates.content_duplicates_nonzero),
        zero_byte_duplicate_groups=len(duplicates.zero_byte_identical),
        zero_byte_duplicate_files=sum(len(group) for group in duplicates.zero_byte_identical),
        same_name_different_content=len(duplicates.same_name_different_content),
        result=result,
        warnings=warnings,
        errors=errors,
        source_trees=[source_tree_public(tree) for tree in (source_trees or [])],
        previous_inventory_files=previous_inventory_files,
    )


def _write_outputs(dest: Path, inventory: dict, report_text: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    inventory_path = dest / "inventory.json"
    report_path = dest / "validation_report.md"
    inventory_path.write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(report_text, encoding="utf-8")


def _previous_inventory_total(dest: Path) -> int | None:
    previous = dest / "inventory.json"
    if not previous.is_file():
        return None
    try:
        payload = json.loads(previous.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    summary = payload.get("summary") or {}
    total = summary.get("totalFiles")
    return int(total) if isinstance(total, int) else None


def ingest(wall_id: str, root: Path) -> IngestionSummary:
    incoming = incoming_dir(root, wall_id)
    dest = output_dir(root, wall_id)
    generated_at = datetime.now(timezone.utc).isoformat()
    previous_total = _previous_inventory_total(dest)

    wall_exists = incoming.exists()
    wall_accessible = wall_exists and incoming.is_dir()
    listing_error = None
    records: list[InventoryRecord] = []
    before: dict[str, str] = {}
    after: dict[str, str] = {}
    incoming_unchanged = True
    trees = discover_source_trees(root, wall_id) if wall_exists else []

    if wall_accessible:
        try:
            before = snapshot_source_trees(trees)
            for tree, path, rel in iter_tree_files(trees):
                record = build_record(tree["path"], path, relative_path=rel)
                record.extra["sourceTree"] = tree["id"]
                records.append(record)
            associate_sidecars(records)
            after = snapshot_source_trees(trees)
            incoming_unchanged = before == after
        except OSError as exc:
            listing_error = f"cannot list incoming files: {exc}"
            incoming_unchanged = False

    duplicates = find_duplicates(records)
    datasets = discover_tileset_datasets(records, incoming) if wall_accessible and listing_error is None else []
    warnings = collect_warnings(records, duplicates) if wall_accessible and listing_error is None else []
    result, errors = decide_result(
        wall_exists=wall_exists,
        wall_accessible=wall_accessible,
        images_readable=sum(1 for rec in records if is_readable_image(rec)),
        incoming_unchanged=incoming_unchanged,
        warnings=warnings,
        listing_error=listing_error,
    )
    if before and after and before != after:
        changed = sorted(set(before) ^ set(after))
        errors.append("changed incoming paths: " + ", ".join(changed[:20]))

    summary = build_summary(
        wall_id,
        incoming,
        records,
        result,
        warnings,
        errors,
        duplicates,
        datasets,
        source_trees=trees,
        previous_inventory_files=previous_total,
    )
    inventory = {
        "schemaVersion": SCHEMA_VERSION,
        "wallId": wall_id,
        "incomingRoot": str(incoming),
        "sourceTrees": [source_tree_public(tree) for tree in trees],
        "previousInventoryFiles": previous_total if previous_total is not None else MISSING,
        "generatedAt": generated_at,
        "result": result.value,
        "summary": {
            "totalFiles": summary.total_files,
            "byType": summary.by_type,
            "imagesDetected": summary.images_detected,
            "imagesReadable": summary.images_readable,
            "imagesWithExif": summary.images_with_exif,
            "imagesWithGps": summary.images_with_gps,
            "cameraModels": summary.camera_models,
            "rtkCandidates": summary.rtk_candidates,
            "rtkTypes": summary.rtk_types,
            "rtkParsed": summary.rtk_parsed,
            "rtkParserNotImplemented": summary.rtk_parser_not_implemented,
            "geospatialSidecars": summary.geospatial_sidecars,
            "standaloneModels": summary.standalone_models,
            "standaloneModelFormats": summary.standalone_model_formats,
            "tilesetJsonFound": summary.tileset_json_found,
            "tilesetJsonCount": summary.tileset_json_count,
            "tilesetDatasets": summary.tileset_datasets,
            "b3dmTiles": summary.b3dm_tiles,
            "b3dmInDatasets": summary.b3dm_in_datasets,
            "b3dmUnreferenced": summary.b3dm_unreferenced,
            "routeGeometryDetected": summary.route_geometry_detected,
            "routeFormats": summary.route_formats,
            "structuredData": summary.structured_data,
            "metadata": summary.metadata,
            "unknown": summary.unknown,
            "exactDuplicateGroups": summary.exact_duplicate_groups,
            "exactDuplicateExtraFiles": summary.exact_duplicate_files,
            "nonzeroDuplicateGroups": summary.nonzero_duplicate_groups,
            "nonzeroDuplicateExtraFiles": summary.nonzero_duplicate_files,
            "zeroByteIdenticalGroups": summary.zero_byte_duplicate_groups,
            "zeroByteIdenticalFiles": summary.zero_byte_duplicate_files,
            "sameFilenameDifferentContentGroups": summary.same_name_different_content,
            "previousInventoryFiles": previous_total if previous_total is not None else MISSING,
            "filesAddedSincePreviousInventory": (
                summary.total_files - previous_total if previous_total is not None else MISSING
            ),
        },
        "datasets": {"cesium3dTiles": datasets},
        "duplicates": {
            "exactDuplicates": duplicates.exact_duplicates,
            "contentDuplicatesNonZero": duplicates.content_duplicates_nonzero,
            "zeroByteIdentical": duplicates.zero_byte_identical,
            "sameFilenameSameContent": duplicates.same_name_same_content,
            "sameFilenameDifferentContent": duplicates.same_name_different_content,
        },
        "warnings": warnings,
        "errors": errors,
        "files": [rec.to_json() for rec in records],
    }
    _write_outputs(dest, inventory, render_validation_report(summary))
    return summary
