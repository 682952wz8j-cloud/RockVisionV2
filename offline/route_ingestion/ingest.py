"""Build Gate 5A ingested route artifacts. Vertices are copied, never fitted."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from .schema import (
    COORDINATE_FRAME,
    INGESTED_KIND,
    PROVENANCE,
    SCHEMA_VERSION,
)


def polyline_sha256(points: list[list[float]]) -> str:
    payload = bytearray()
    for point in points:
        if len(point) != 3:
            raise ValueError("polyline vertex must be xyz")
        for coord in point:
            payload.extend(struct.pack("<d", float(coord)))
    return hashlib.sha256(bytes(payload)).hexdigest()


def build_ingested_route(
    *,
    wall_id: str,
    run_id: str,
    model_fingerprint: str,
    source: dict,
    metadata: dict,
    geometry: dict,
) -> dict:
    polyline = geometry["ingestedVertices"]
    digest = polyline_sha256(polyline)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": INGESTED_KIND,
        "routeId": metadata["routeId"],
        "routeName": metadata["routeName"],
        "grade": metadata["grade"],
        "quickdraws": metadata["quickdraws"],
        "boltCount": metadata["boltCount"],
        "anchorCount": metadata["anchorCount"],
        "wallId": wall_id,
        "wallBuildRunId": run_id,
        "colmapModelFingerprint": model_fingerprint,
        "source": {
            "path": source["relativePath"],
            "sha256": source["sha256"],
            "sizeBytes": source["fileSize"],
        },
        "identityBasis": metadata["identityBasis"],
        "coordinateFrame": COORDINATE_FRAME,
        "provenance": PROVENANCE,
        "dummyOriginExcluded": bool(geometry["dummyOriginExcluded"]),
        "pointCount": geometry["pointCount"],
        "sourceVertexCount": geometry["sourceVertexCount"],
        "polyline": polyline,
        "polylineSha256": digest,
        "bbox": geometry["bbox"],
        "createdBy": geometry["createdBy"],
        "geometryUnmodified": True,
        "snappedOrFitted": False,
        "productionRoutePackage": "NOT_CREATED",
        "rendering": "NOT_STARTED",
        "FIRST_ROUTE_FROZEN": False,
        "gate5aPass": False,
        "notAStage5Release": True,
        "status": "INGESTED_FOR_FIELD_IPHONE_TEST",
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
