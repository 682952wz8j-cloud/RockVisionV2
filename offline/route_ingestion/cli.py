"""CLI for `rockvision ingest-routes`."""

from __future__ import annotations

from pathlib import Path

from .pipeline import run_route_ingestion
from .schema import GATE_STOP


def run_ingest_routes(
    wall_id: str,
    root: Path,
    *,
    run_id: str,
    colmap_model_fingerprint: str,
) -> int:
    job = run_route_ingestion(
        wall_id=wall_id,
        root=root,
        run_id=run_id,
        expected_fingerprint=colmap_model_fingerprint,
    )
    print(f"Wall ID: {job.get('wallId') or wall_id}")
    print(f"runId: {job.get('wallBuildRunId') or run_id}")
    print(f"STATUS: {job.get('status')}")
    if job.get("reasonCode"):
        print(f"reasonCode: {job['reasonCode']}")
        print(f"error: {job.get('error')}")
    print(f"discoveredDxf: {job.get('discoveredDxf')}")
    for route in job.get("routes") or []:
        print(
            f"  {route['sourceFilename']}: vertices={route['vertexCount']} "
            f"name={route['routeName']} {route['grade']} {route['quickdraws']}"
        )
    loc = job.get("localizationPackage") or {}
    print(f"localizationPackage: {loc.get('packageState')} localizationReady={loc.get('localizationReady')}")
    ios = job.get("iosLocalTest") or {}
    if ios.get("iosLocalTestDir"):
        print(f"iosLocalTestDir: {ios['iosLocalTestDir']}")
    print("This is NOT a Stage 5 release, publish, or production routes.json.")
    return 1 if job.get("status") == GATE_STOP else 0
