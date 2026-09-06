"""Construct a local localization-package candidate from one wall_build run.

Does not publish. Does not write COS or published/catalog.json.
releaseId r000000 is a local candidate id, not a catalog release.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from offline.colmap.source_identity import evaluate_colmap_source_identity
from offline.stage2_selection.sources import sources_from_selection

from .cloud_manifest import local_cloud_manifest
from .construct import write_package_candidate
from .schema import (
    COLMAP_IDENTITY_PROVEN,
    ENVIRONMENT_PRODUCTION,
    PACKAGE_SCHEMA,
    STATE_CONSTRUCTED,
    TYPE_DESCRIPTORS,
    TYPE_LANDMARKS,
    TYPE_S_WALL_COLMAP,
)
from .validate import PackageValidationResult, validate_package_dir

LOCAL_CANDIDATE_RELEASE_ID = "r000000"


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def construct_and_validate_from_run(
    *,
    wall_id: str,
    root: Path,
    run_id: str,
    run_dir: Path,
    freeze_dir: Path,
) -> dict:
    """Bind package files to this run directory. Validate without publishing."""
    sim3_path = run_dir / "metric_registration" / "S_wall_colmap.json"
    identity_path = run_dir / "colmap" / "colmap_source_identity.json"
    selection_path = run_dir / "stage2_input_selection.json"
    descriptors = (freeze_dir / "descriptors.bin").read_bytes()
    landmarks = (freeze_dir / "landmarks.json").read_bytes()
    sim3 = sim3_path.read_bytes()
    freeze = _read_json(freeze_dir / "freeze.json") or {}
    selection = _read_json(selection_path) or {}
    identity = _read_json(identity_path) or {}
    incoming = root / "incoming" / wall_id
    sources = sources_from_selection(selection)
    evaluated = None
    if sources is not None:
        evaluated = evaluate_colmap_source_identity(incoming, sources, run_dir / "colmap")
    evidence_identity = dict(identity)
    if evaluated and evaluated.get("colmapSourceIdentityExecutionAllowed"):
        evidence_identity["colmapSourceIdentityExecutionAllowed"] = True
        evidence_identity["colmapSourceIdentityReasonCode"] = evaluated.get(
            "colmapSourceIdentityReasonCode"
        ) or COLMAP_IDENTITY_PROVEN
        if evaluated.get("modelFingerprint"):
            evidence_identity["modelFingerprint"] = evaluated["modelFingerprint"]
    jpeg = (
        (selection.get("selectedCapture") or {}).get("sourceChecksums")
        or selection.get("sourceChecksums")
        or {}
    )
    pq_evidence = _read_json(run_dir / "positioning_quality.json") or {}
    height_evidence = _read_json(run_dir / "height_vertical_datum.json") or {}
    desc_spec = {
        "assetId": "stage3-descriptors",
        "type": TYPE_DESCRIPTORS,
        "schema": "RVS1",
        "sha256": _sha_bytes(descriptors),
        "bytes": len(descriptors),
    }
    land_spec = {
        "assetId": "stage3-landmarks",
        "type": TYPE_LANDMARKS,
        "schema": 1,
        "sha256": _sha_bytes(landmarks),
        "bytes": len(landmarks),
    }
    metric_spec = {
        "assetId": "s-wall-colmap",
        "type": TYPE_S_WALL_COLMAP,
        "status": "VALIDATED",
        "source": "S_wall_colmap.json",
        "sha256": _sha_bytes(sim3),
        "bytes": len(sim3),
    }
    fingerprint = evidence_identity.get("modelFingerprint")
    package = {
        "schema": PACKAGE_SCHEMA,
        "wallId": wall_id,
        "releaseId": LOCAL_CANDIDATE_RELEASE_ID,
        "environment": ENVIRONMENT_PRODUCTION,
        "capabilities": {"localizationReady": False, "routeArReady": False},
        "sourceBuild": {
            "runId": run_id,
            "selection": {
                "schema": selection.get("schemaVersion") or "stage2_input_selection.4",
                "selectionStatus": selection.get("selectionStatus"),
            },
            "selectedSourceJpegSha256": jpeg,
            "positioningQuality": {
                "positioningQualityExecutionAllowed": bool(
                    pq_evidence.get("positioningQualityExecutionAllowed")
                ),
                "positioningQualityReasonCode": pq_evidence.get("positioningQualityReasonCode"),
            },
            "heightDatum": {
                "heightGateExecutionAllowed": bool(height_evidence.get("heightGateExecutionAllowed"))
            },
            "colmapSourceIdentity": {
                "modelFingerprint": fingerprint,
                "colmapSourceIdentityReasonCode": evidence_identity.get("colmapSourceIdentityReasonCode")
                or COLMAP_IDENTITY_PROVEN,
                "colmapSourceIdentityExecutionAllowed": True,
            },
        },
        "metricTransform": metric_spec,
        "stage3": {
            "descriptors": desc_spec,
            "landmarks": land_spec,
            "freezeIdentity": {
                "colmapModelFingerprint": freeze.get("colmapModelFingerprint"),
                "wallBuildRunId": freeze.get("wallBuildRunId"),
            },
        },
        "routes": {"present": False, "authorized": False},
        "packageState": STATE_CONSTRUCTED,
        "notACatalogRelease": True,
    }
    evidence_selection = dict(selection)
    if jpeg and "selectedImageSha256" not in evidence_selection:
        evidence_selection["selectedImageSha256"] = jpeg
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = local_cloud_manifest(
        wall_id=wall_id,
        release_id=LOCAL_CANDIDATE_RELEASE_ID,
        created_at=created_at,
        descriptors=desc_spec,
        landmarks=land_spec,
        metric=metric_spec,
    )
    package_root = run_dir / "localization_package"
    write_package_candidate(
        package_root,
        package=package,
        cloud_manifest=manifest,
        assets={
            "stage3-descriptors": descriptors,
            "stage3-landmarks": landmarks,
            "s-wall-colmap": sim3,
        },
        evidence={
            "stage2_input_selection.json": evidence_selection,
            "positioning_quality.json": _read_json(run_dir / "positioning_quality.json") or {},
            "height_vertical_datum.json": _read_json(run_dir / "height_vertical_datum.json") or {},
            "colmap_source_identity.json": evidence_identity,
            "freeze.json": freeze,
        },
    )
    result: PackageValidationResult = validate_package_dir(package_root)
    return {
        "packageDir": str(package_root),
        "releaseId": LOCAL_CANDIDATE_RELEASE_ID,
        "notACatalogRelease": True,
        "constructed": True,
        "packageState": result.package_state,
        "localizationReady": result.localization_ready,
        "reasonCodes": result.reason_codes,
        "published": False,
    }
