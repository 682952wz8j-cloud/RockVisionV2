from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RawAssetType(str, Enum):
    IMAGE = "image"
    RTK_GNSS = "rtkGnss"
    MODEL_3D = "model3D"
    ROUTE_GEOMETRY = "routeGeometry"
    STRUCTURED_DATA = "structuredData"
    METADATA = "metadata"
    GEOSPATIAL_SIDECAR = "geospatialSidecar"
    UNKNOWN = "unknown"


class ValidationStatus(str, Enum):
    OK = "ok"
    DETECTED_UNPARSED = "detected_unparsed"
    PARSER_NOT_IMPLEMENTED = "parser_not_implemented"
    MISSING_METADATA = "missing_metadata"
    UNREADABLE = "unreadable"
    UNSUPPORTED_DECODE = "unsupported_decode"
    UNKNOWN = "unknown"


class RunResult(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS WITH WARNINGS"
    FAIL = "FAIL"


MISSING = "missing"


@dataclass
class ImageInfo:
    pixel_width: int | str = MISSING
    pixel_height: int | str = MISSING
    has_exif: bool | str = MISSING
    camera_make: str = MISSING
    camera_model: str = MISSING
    focal_length: str = MISSING
    focal_length_35mm: str = MISSING
    capture_timestamp: str = MISSING
    gps_latitude: str = MISSING
    gps_longitude: str = MISSING
    gps_altitude: str = MISSING
    orientation: str = MISSING
    image_format: str = MISSING
    lens_model: str = MISSING


@dataclass
class InventoryRecord:
    relative_path: str
    filename: str
    extension: str
    file_size: int
    sha256: str
    detected_type: RawAssetType
    detection_method: str
    validation_status: ValidationStatus
    mime_or_signature: str = MISSING
    creation_time: str = MISSING
    modified_time: str = MISSING
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        data = {
            "relativePath": self.relative_path,
            "filename": self.filename,
            "extension": self.extension,
            "fileSize": self.file_size,
            "sha256": self.sha256,
            "detectedType": self.detected_type.value,
            "detectionMethod": self.detection_method,
            "validationStatus": self.validation_status.value,
            "mimeOrSignature": self.mime_or_signature,
            "creationTime": self.creation_time,
            "modifiedTime": self.modified_time,
        }
        data.update(self.extra)
        return data


@dataclass
class DuplicateGroups:
    exact_duplicates: list[list[str]]
    content_duplicates_nonzero: list[list[str]]
    zero_byte_identical: list[list[str]]
    same_name_same_content: list[list[str]]
    same_name_different_content: list[list[str]]


@dataclass
class IngestionSummary:
    wall_id: str
    incoming_root: str
    total_files: int
    by_type: dict[str, int]
    images_detected: int
    images_readable: int
    images_with_exif: int
    images_with_gps: int
    camera_models: list[str]
    rtk_candidates: int
    rtk_parsed: int
    rtk_parser_not_implemented: int
    rtk_types: list[str]
    standalone_models: int
    standalone_model_formats: list[str]
    geospatial_sidecars: int
    tileset_json_found: bool
    tileset_json_count: int
    tileset_datasets: int
    b3dm_tiles: int
    b3dm_in_datasets: int
    b3dm_unreferenced: int
    route_geometry_detected: int
    route_formats: list[str]
    structured_data: int
    metadata: int
    unknown: int
    exact_duplicate_groups: int
    exact_duplicate_files: int
    nonzero_duplicate_groups: int
    nonzero_duplicate_files: int
    zero_byte_duplicate_groups: int
    zero_byte_duplicate_files: int
    same_name_different_content: int
    result: RunResult
    warnings: list[str]
    errors: list[str]
    source_trees: list[dict] = field(default_factory=list)
    previous_inventory_files: int | None = None
