"""Validate ingested routes, freeze, bind, and the existing localization package."""

from __future__ import annotations

from pathlib import Path

from offline.ingestion.hashing import sha256_file
from offline.localization_package.schema import STATE_PACKAGE_READY
from offline.localization_package.validate import validate_package_dir

from .ingest import polyline_sha256
from .schema import (
    COORDINATE_FRAME,
    FIXTURE_KIND,
    FIXTURE_SCHEMA,
    INGESTED_KIND,
    REASON_COORDINATE_FRAME,
    REASON_GEOMETRY_INVALID,
    REASON_LOCALIZATION,
    REASON_PROVENANCE,
    SCHEMA_VERSION,
)


class RouteValidateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_ingested_route(ingested: dict, source_path: Path, source_sha256: str) -> None:
    if ingested.get("schemaVersion") != SCHEMA_VERSION or ingested.get("kind") != INGESTED_KIND:
        raise RouteValidateError(REASON_PROVENANCE, "ingested artifact is not gate5a.ingested.route.1")
    if ingested.get("coordinateFrame") != COORDINATE_FRAME:
        raise RouteValidateError(REASON_COORDINATE_FRAME, "coordinateFrame is not WallMetricMeters")
    polyline = ingested.get("polyline")
    if not isinstance(polyline, list) or ingested.get("pointCount") != len(polyline):
        raise RouteValidateError(REASON_GEOMETRY_INVALID, "pointCount does not match polyline")
    if ingested.get("snappedOrFitted") is not False or ingested.get("geometryUnmodified") is not True:
        raise RouteValidateError(REASON_GEOMETRY_INVALID, "geometry was marked modified")
    digest = polyline_sha256(polyline)
    if digest != ingested.get("polylineSha256"):
        raise RouteValidateError(REASON_PROVENANCE, "polylineSha256 does not match vertices")
    if not source_path.is_file() or sha256_file(source_path) != source_sha256:
        raise RouteValidateError(REASON_PROVENANCE, "source DXF sha256 mismatch at validate")
    if ingested.get("productionRoutePackage") != "NOT_CREATED":
        raise RouteValidateError(REASON_PROVENANCE, "production route package must not be created")


def validate_ios_fixture(fixture: dict, ingested: dict) -> None:
    if fixture.get("schemaVersion") != FIXTURE_SCHEMA or fixture.get("kind") != FIXTURE_KIND:
        raise RouteValidateError(REASON_PROVENANCE, "iOS fixture is not gate5c.development.route.fixture.1")
    if fixture.get("polyline") != ingested.get("polyline"):
        raise RouteValidateError(REASON_GEOMETRY_INVALID, "iOS fixture polyline diverged from ingested")
    if fixture.get("polylineSha256") != ingested.get("polylineSha256"):
        raise RouteValidateError(REASON_PROVENANCE, "iOS fixture hash diverged from ingested")
    if fixture.get("notAProductionRoutePackage") is not True:
        raise RouteValidateError(REASON_PROVENANCE, "iOS fixture must not be a production route package")


def validate_localization_package(package_dir: Path) -> dict:
    result = validate_package_dir(package_dir)
    if result.package_state != STATE_PACKAGE_READY or not result.localization_ready:
        raise RouteValidateError(
            REASON_LOCALIZATION,
            f"localization package not ready: {result.package_state} {result.reason_codes}",
        )
    if result.route_ar_ready:
        raise RouteValidateError(REASON_PROVENANCE, "localization package must not set routeArReady")
    return {
        "packageDir": str(package_dir),
        "packageState": result.package_state,
        "localizationReady": result.localization_ready,
        "routeArReady": result.route_ar_ready,
        "reasonCodes": result.reason_codes,
    }
