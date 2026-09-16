"""Discover → freeze → ingest → bind → iOS assets → validate. Stop before field iPhone."""

from __future__ import annotations

import json
from pathlib import Path

from offline.ingestion.pipeline import incoming_dir

from .assets import write_ios_local_test_assets
from .bind import RouteBindError, bind_production_run
from .discover import RouteDiscoveryError, discover_route_dxf
from .freeze import RouteFreezeError, build_route_input_freeze, utc_now, verify_route_input_freeze
from .ingest import build_ingested_route, write_json
from .metadata import RouteMetadataError, metadata_from_filename
from .parse import RouteParseError, ingest_polyline_from_dxf
from .schema import (
    GATE_READY_FOR_FIELD_IPHONE,
    GATE_STOP,
    JOB_SCHEMA,
    REASON_BIND_FAILED,
)
from .validate import RouteValidateError, validate_ingested_route, validate_ios_fixture, validate_localization_package


class RouteIngestError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str, extra: dict | None = None) -> dict:
    payload = {
        "schemaVersion": JOB_SCHEMA,
        "status": GATE_STOP,
        "reasonCode": code,
        "error": message,
        "fieldIphoneTestBoundary": True,
        "published": False,
        "stage5Release": False,
        "productionRoutePackage": False,
    }
    if extra:
        payload.update(extra)
    return payload


def output_dir(root: Path, wall_id: str, run_id: str) -> Path:
    return root / "offline" / "work" / wall_id / "route_ingestion" / f"bound_{run_id}"


def run_route_ingestion(
    *,
    wall_id: str,
    root: Path,
    run_id: str,
    expected_fingerprint: str,
) -> dict:
    try:
        bind = bind_production_run(root, wall_id, run_id, expected_fingerprint=expected_fingerprint)
        discovered = discover_route_dxf(root, wall_id)
        incoming = incoming_dir(root, wall_id)
        freeze = build_route_input_freeze(wall_id=wall_id, incoming=incoming, dxf_files=discovered["dxfFiles"])
        dest = output_dir(root, wall_id, run_id)
        dest.mkdir(parents=True, exist_ok=True)
        ingested_dir = dest / "ingested"
        ingested_records = []
        for item in discovered["dxfFiles"]:
            path = incoming / item["relativePath"]
            metadata = metadata_from_filename(item["sourceFilename"])
            geometry = ingest_polyline_from_dxf(path)
            ingested = build_ingested_route(
                wall_id=wall_id,
                run_id=run_id,
                model_fingerprint=bind.model_fingerprint,
                source=item,
                metadata=metadata,
                geometry=geometry,
            )
            rel = f"ingested/{metadata['routeId']}.json"
            write_json(dest / rel, ingested)
            validate_ingested_route(ingested, path, item["sha256"])
            ingested_records.append(
                {
                    "ingested": ingested,
                    "ingestedRel": rel,
                    "source": item,
                    "metadata": metadata,
                    "vertexCount": ingested["pointCount"],
                }
            )
        verify_route_input_freeze(incoming, freeze)
        assets = write_ios_local_test_assets(
            dest,
            wall_id=wall_id,
            run_id=run_id,
            model_fingerprint=bind.model_fingerprint,
            localization_package_dir=bind.localization_package_dir,
            ingested_records=ingested_records,
        )
        for record in ingested_records:
            fixture_path = Path(assets["iosLocalTestDir"]) / f"{record['ingested']['routeId']}.json"
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
            validate_ios_fixture(fixture, record["ingested"])
        loc = validate_localization_package(bind.localization_package_dir)
        write_json(dest / "route_input_freeze.json", freeze)
        job = {
            "schemaVersion": JOB_SCHEMA,
            "status": GATE_READY_FOR_FIELD_IPHONE,
            "wallId": wall_id,
            "wallBuildRunId": run_id,
            "colmapModelFingerprint": bind.model_fingerprint,
            "discoveredDxf": [item["sourceFilename"] for item in discovered["dxfFiles"]],
            "routeCount": len(ingested_records),
            "routes": [
                {
                    "routeId": rec["ingested"]["routeId"],
                    "routeName": rec["ingested"]["routeName"],
                    "grade": rec["ingested"]["grade"],
                    "quickdraws": rec["ingested"]["quickdraws"],
                    "sourceFilename": rec["source"]["sourceFilename"],
                    "vertexCount": rec["vertexCount"],
                    "sourceVertexCount": rec["ingested"]["sourceVertexCount"],
                    "dummyOriginExcluded": rec["ingested"]["dummyOriginExcluded"],
                    "polylineSha256": rec["ingested"]["polylineSha256"],
                    "ingestedPath": str(dest / rec["ingestedRel"]),
                }
                for rec in ingested_records
            ],
            "routeInputFreeze": str(dest / "route_input_freeze.json"),
            "freezeSha256": freeze["freezeSha256"],
            "iosLocalTest": assets,
            "localizationPackage": loc,
            "fieldIphoneTestBoundary": True,
            "iosRuntimeLoadsJinshidongAssets": False,
            "published": False,
            "stage5Release": False,
            "productionRoutePackage": False,
            "createdAt": utc_now(),
        }
        write_json(dest / "job.json", job)
        return job
    except (
        RouteBindError,
        RouteDiscoveryError,
        RouteFreezeError,
        RouteMetadataError,
        RouteParseError,
        RouteValidateError,
        RouteIngestError,
    ) as exc:
        code = getattr(exc, "code", REASON_BIND_FAILED)
        return _fail(code, str(exc))
