from __future__ import annotations

from .types import IngestionSummary, RunResult


def render_validation_report(summary: IngestionSummary) -> str:
    lines = [
        "# Raw Data Ingestion Report",
        "",
        f"Wall ID: {summary.wall_id}",
        f"Incoming: `{summary.incoming_root}`",
        f"Total files: {summary.total_files}",
        (
            f"Previous inventory files: {summary.previous_inventory_files}; "
            f"added since previous: {summary.total_files - summary.previous_inventory_files}"
            if summary.previous_inventory_files is not None
            else "Previous inventory files: none"
        ),
        "",
        "Source trees (read-only; incoming files are not moved):",
    ]
    if summary.source_trees:
        for tree in summary.source_trees:
            prefix = tree.get("relativePrefix") or "."
            lines.append(f"  - {tree.get('id')}: `{tree.get('path')}` as `{prefix}`")
    else:
        lines.append("  - none")
    lines.extend(
        [
        "",
        "Images:",
        f"  Detected: {summary.images_detected}",
        f"  Readable: {summary.images_readable}",
        f"  With EXIF: {summary.images_with_exif}",
        f"  With GPS: {summary.images_with_gps}",
        f"  Camera models: {', '.join(summary.camera_models) if summary.camera_models else 'none'}",
        "",
        "RTK / GNSS:",
        f"  Candidates: {summary.rtk_candidates}",
        f"  Types: {', '.join(summary.rtk_types) if summary.rtk_types else 'none'}",
        f"  Parsed: {summary.rtk_parsed}",
        f"  Parser not yet implemented: {summary.rtk_parser_not_implemented}",
        "",
        "Geospatial Sidecars:",
        f"  Detected: {summary.geospatial_sidecars}",
        "",
        "3D Models:",
        f"  Standalone: {summary.standalone_models}",
        f"  Format: {', '.join(summary.standalone_model_formats) if summary.standalone_model_formats else 'none'}",
        "",
        "3D Tiles:",
        f"  tileset.json found: {'yes' if summary.tileset_json_found else 'no'}",
        f"  tileset.json files: {summary.tileset_json_count}",
        f"  Datasets: {summary.tileset_datasets}",
        f"  B3DM tiles: {summary.b3dm_tiles}",
        f"  B3DM in datasets: {summary.b3dm_in_datasets}",
        f"  B3DM unreferenced: {summary.b3dm_unreferenced}",
        "",
        "Route Geometry:",
        f"  Detected: {summary.route_geometry_detected}",
        f"  Format: {', '.join(summary.route_formats) if summary.route_formats else 'none'}",
        "",
        "Structured Data / Metadata:",
        f"  Structured data: {summary.structured_data}",
        f"  Metadata candidates: {summary.metadata}",
        "",
        "Unknown:",
        f"  {summary.unknown}",
        "",
        "Duplicates:",
        f"  Non-zero content duplicate groups: {summary.nonzero_duplicate_groups}",
        f"  Non-zero content duplicate extra files: {summary.nonzero_duplicate_files}",
        f"  Zero-byte identical groups: {summary.zero_byte_duplicate_groups}",
        f"  Zero-byte identical files: {summary.zero_byte_duplicate_files}",
        f"  Same filename / different content groups: {summary.same_name_different_content}",
        "",
        "Validation:",
        f"  {summary.result.value}",
        ]
    )
    if summary.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {item}" for item in summary.warnings)
    if summary.errors:
        lines.extend(["", "Errors:"])
        lines.extend(f"- {item}" for item in summary.errors)
    lines.append("")
    return "\n".join(lines)


def print_console_summary(summary: IngestionSummary) -> None:
    print(f"Wall ID: {summary.wall_id}")
    print(f"Total files: {summary.total_files}")
    print(f"Images: detected {summary.images_detected}, readable {summary.images_readable}, GPS {summary.images_with_gps}")
    print(f"RTK / GNSS: candidates {summary.rtk_candidates} ({', '.join(summary.rtk_types) or 'none'})")
    print(f"Geospatial sidecars: {summary.geospatial_sidecars}")
    print(f"3D Tiles datasets: {summary.tileset_datasets}; B3DM tiles: {summary.b3dm_tiles}")
    print(f"Standalone 3D models: {summary.standalone_models}")
    print(f"Route Geometry: {summary.route_geometry_detected}")
    print(f"Unknown: {summary.unknown}")
    print(
        f"Duplicates: non-zero groups {summary.nonzero_duplicate_groups}; "
        f"zero-byte files {summary.zero_byte_duplicate_files}"
    )
    print(f"Validation: {summary.result.value}")
    if summary.result == RunResult.FAIL:
        for error in summary.errors:
            print(f"ERROR: {error}")
