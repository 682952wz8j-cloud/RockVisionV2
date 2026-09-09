"""Existing Gate 5C iOS route fixture files. Not a production routes.json."""

from __future__ import annotations

from pathlib import Path

from .ingest import write_json
from .schema import FIXTURE_KIND, FIXTURE_SCHEMA, BUNDLE_SCHEMA


def build_ios_fixture(*, ingested: dict, ingested_rel: str) -> dict:
    return {
        "schemaVersion": FIXTURE_SCHEMA,
        "kind": FIXTURE_KIND,
        "developmentValidationOnly": True,
        "notAProductionRoutePackage": True,
        "sourceArtifact": ingested_rel,
        "routeId": ingested["routeId"],
        "routeName": ingested["routeName"],
        "grade": ingested.get("grade"),
        "quickdraws": ingested.get("quickdraws"),
        "wallId": ingested["wallId"],
        "wallBuildRunId": ingested["wallBuildRunId"],
        "colmapModelFingerprint": ingested["colmapModelFingerprint"],
        "coordinateFrame": ingested["coordinateFrame"],
        "provenance": ingested["provenance"],
        "dummyOriginExcluded": ingested["dummyOriginExcluded"],
        "pointCount": ingested["pointCount"],
        "polyline": ingested["polyline"],
        "polylineSha256": ingested["polylineSha256"],
    }


def write_ios_local_test_assets(
    dest: Path,
    *,
    wall_id: str,
    run_id: str,
    model_fingerprint: str,
    localization_package_dir: Path,
    ingested_records: list[dict],
) -> dict:
    fixtures_dir = dest / "ios_local_test"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    bundle_routes = []
    for record in ingested_records:
        ingested = record["ingested"]
        ingested_rel = record["ingestedRel"]
        fixture = build_ios_fixture(ingested=ingested, ingested_rel=ingested_rel)
        fixture_name = f"{ingested['routeId']}.json"
        write_json(fixtures_dir / fixture_name, fixture)
        bundle_routes.append(
            {
                "routeId": ingested["routeId"],
                "routeName": ingested["routeName"],
                "grade": ingested.get("grade"),
                "quickdraws": ingested.get("quickdraws"),
                "pointCount": ingested["pointCount"],
                "polylineSha256": ingested["polylineSha256"],
                "fixturePath": f"ios_local_test/{fixture_name}",
                "ingestedPath": ingested_rel,
            }
        )
    bundle = {
        "schemaVersion": BUNDLE_SCHEMA,
        "kind": "development_validation_route_bundle",
        "developmentValidationOnly": True,
        "notAProductionRoutePackage": True,
        "notAStage5Release": True,
        "wallId": wall_id,
        "wallBuildRunId": run_id,
        "colmapModelFingerprint": model_fingerprint,
        "localizationPackageDir": str(localization_package_dir),
        "routes": bundle_routes,
    }
    bundle_path = fixtures_dir / "route_bundle.json"
    write_json(bundle_path, bundle)
    return {
        "iosLocalTestDir": str(fixtures_dir),
        "routeBundle": str(bundle_path),
        "fixtures": [str(fixtures_dir / item["fixturePath"].split("/")[-1]) for item in bundle_routes],
        "localizationPackageDir": str(localization_package_dir),
    }
