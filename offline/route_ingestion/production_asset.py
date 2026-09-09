"""Production runtime route asset. Geometry copied from ingested DXF polylines."""

from __future__ import annotations

from .ingest import polyline_sha256
from .schema import COORDINATE_FRAME, INGESTED_KIND, PROVENANCE, SCHEMA_VERSION

ROUTE_ASSET_SCHEMA = "cragpal.wall-routes.v1"
TYPE_WALL_ROUTES = "wall_routes_json"
ASSET_ID = "wall-routes"

EXPECTED_JINSHIDONG_ROUTE_IDS = (
    "jinshidong_lucky_baby",
    "jinshidong_shui_tai_shen",
    "jinshidong_mei_xiang_hao",
    "jinshidong_long_zhua_shou",
)


class RouteAssetError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def build_production_route_asset(
    *,
    wall_id: str,
    release_id: str,
    run_id: str,
    model_fingerprint: str,
    ingested_records: list[dict],
) -> dict:
    routes = []
    for ingested in ingested_records:
        routes.append(_runtime_route(ingested, wall_id=wall_id, run_id=run_id, fingerprint=model_fingerprint))
    route_ids = tuple(item["routeId"] for item in routes)
    if route_ids != EXPECTED_JINSHIDONG_ROUTE_IDS and wall_id == "wall_jinshidong_01":
        raise RouteAssetError("ROUTE_ASSET_INVALID", "Jinshidong production routes must be the frozen 4-route set")
    return {
        "schema": ROUTE_ASSET_SCHEMA,
        "wallId": wall_id,
        "releaseId": release_id,
        "wallBuildRunId": run_id,
        "colmapModelFingerprint": model_fingerprint,
        "coordinateFrame": COORDINATE_FRAME,
        "routes": routes,
    }


def decode_production_route_asset(
    payload: object,
    *,
    wall_id: str,
    release_id: str,
    run_id: str,
    model_fingerprint: str,
) -> dict:
    if not isinstance(payload, dict):
        raise RouteAssetError("ROUTE_ASSET_INVALID", "wall-routes must be an object")
    if payload.get("schema") != ROUTE_ASSET_SCHEMA:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "schema must be cragpal.wall-routes.v1")
    if payload.get("wallId") != wall_id:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "wall-routes wallId mismatch")
    if payload.get("releaseId") != release_id:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "wall-routes releaseId mismatch")
    if payload.get("wallBuildRunId") != run_id:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "wall-routes wallBuildRunId mismatch")
    if payload.get("colmapModelFingerprint") != model_fingerprint:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "wall-routes colmapModelFingerprint mismatch")
    if payload.get("coordinateFrame") != COORDINATE_FRAME:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "wall-routes coordinateFrame mismatch")
    routes = payload.get("routes")
    if not isinstance(routes, list) or not routes:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "wall-routes.routes must be a non-empty array")
    seen: set[str] = set()
    for item in routes:
        _decode_runtime_route(item, wall_id=wall_id, run_id=run_id, fingerprint=model_fingerprint)
        route_id = str(item["routeId"])
        if route_id in seen:
            raise RouteAssetError("ROUTE_ASSET_INVALID", f"duplicate routeId {route_id}")
        seen.add(route_id)
    return payload


def _runtime_route(ingested: dict, *, wall_id: str, run_id: str, fingerprint: str) -> dict:
    if ingested.get("schemaVersion") != SCHEMA_VERSION or ingested.get("kind") != INGESTED_KIND:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "production routes must come from canonical ingested routes")
    if ingested.get("wallId") != wall_id:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "ingested wallId mismatch")
    if ingested.get("wallBuildRunId") != run_id:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "ingested wallBuildRunId mismatch")
    if ingested.get("colmapModelFingerprint") != fingerprint:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "ingested colmapModelFingerprint mismatch")
    polyline = ingested["polyline"]
    digest = polyline_sha256(polyline)
    if digest != ingested.get("polylineSha256"):
        raise RouteAssetError("ROUTE_ASSET_INVALID", "ingested polylineSha256 mismatch")
    source = ingested.get("source") or {}
    return {
        "routeId": ingested["routeId"],
        "routeName": ingested["routeName"],
        "grade": ingested["grade"],
        "quickdraws": ingested["quickdraws"],
        "source": {
            "path": source["path"],
            "sha256": source["sha256"],
            "sizeBytes": source["sizeBytes"],
        },
        "coordinateFrame": COORDINATE_FRAME,
        "provenance": ingested.get("provenance") or PROVENANCE,
        "dummyOriginExcluded": True,
        "pointCount": ingested["pointCount"],
        "polyline": polyline,
        "polylineSha256": digest,
    }


def _decode_runtime_route(item: object, *, wall_id: str, run_id: str, fingerprint: str) -> None:
    if not isinstance(item, dict):
        raise RouteAssetError("ROUTE_ASSET_INVALID", "route entry must be an object")
    for key in ("routeId", "routeName", "grade", "quickdraws"):
        if not isinstance(item.get(key), str) or not item[key]:
            raise RouteAssetError("ROUTE_ASSET_INVALID", f"route.{key} is required")
    if item.get("coordinateFrame") != COORDINATE_FRAME:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "route coordinateFrame mismatch")
    if item.get("dummyOriginExcluded") is not True:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "dummy origin must be excluded")
    polyline = item.get("polyline")
    if not isinstance(polyline, list) or len(polyline) < 2:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "route polyline is invalid")
    if item.get("pointCount") != len(polyline):
        raise RouteAssetError("ROUTE_ASSET_INVALID", "route pointCount mismatch")
    if [0.0, 0.0, 0.0] in polyline:
        raise RouteAssetError("ROUTE_ASSET_INVALID", "dummy origin vertex is forbidden")
    digest = polyline_sha256(polyline)
    if digest != item.get("polylineSha256"):
        raise RouteAssetError("ROUTE_ASSET_INVALID", "polylineSha256 does not match vertices")
    source = item.get("source") or {}
    if not isinstance(source, dict) or not source.get("path") or not source.get("sha256"):
        raise RouteAssetError("ROUTE_ASSET_INVALID", "route DXF source provenance is required")
    if item.get("routeId") == "route_test_01":
        raise RouteAssetError("ROUTE_ASSET_INVALID", "Jiulongfeng route_test_01 is not a Jinshidong production route")
