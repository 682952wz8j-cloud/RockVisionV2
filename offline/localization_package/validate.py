"""Validate a local Production Localization Package candidate.

Construction (files on disk) is not PACKAGE_READY. This module is the
only authority for PACKAGE_READY / LOCALIZATION_READY.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from offline.ingestion.hashing import sha256_file

from .cloud_manifest import CloudManifestError, decode_cloud_manifest_candidate
from .layout import (
    asset_path,
    assets_dir,
    cloud_manifest_path,
    evidence_dir,
    evidence_path,
    package_json_path,
    required_evidence_names,
)
from .package_schema import PackageSchemaError, decode_package_json, is_release_id, is_safe_id
from .schema import (
    COLMAP_IDENTITY_PROVEN,
    ENVIRONMENT_PRODUCTION,
    FORBIDDEN_ROUTE_NAMES,
    POSITIONING_FIXED,
    ReasonCode,
    STATE_NOT_PACKAGE_READY,
    STATE_PACKAGE_READY,
    TYPE_DESCRIPTORS,
    TYPE_LANDMARKS,
    TYPE_S_WALL_COLMAP,
)
from .sim3_asset import assess_sim3_asset, assess_sim3_identity


@dataclass
class PackageValidationResult:
    package_state: str
    localization_ready: bool
    route_ar_ready: bool = False
    reason_codes: list[str] = field(default_factory=list)
    wall_id: str | None = None
    release_id: str | None = None
    environment: str | None = None

    @property
    def ok(self) -> bool:
        return self.package_state == STATE_PACKAGE_READY and self.localization_ready


def validate_package_dir(root: Path) -> PackageValidationResult:
    codes: list[ReasonCode] = []
    if root.name == "published" or (root / "published").exists():
        codes.append(ReasonCode.COS_LAYOUT_FORBIDDEN)

    try:
        payload = json.loads(package_json_path(root).read_text(encoding="utf-8"))
        package = decode_package_json(payload)
    except FileNotFoundError:
        return _fail([ReasonCode.INVALID_PACKAGE_SCHEMA])
    except json.JSONDecodeError:
        return _fail([ReasonCode.INVALID_PACKAGE_SCHEMA])
    except PackageSchemaError as exc:
        return _fail([exc.code])

    wall_id = package["wallId"]
    release_id = package["releaseId"]
    environment = package["environment"]
    if not is_safe_id(wall_id):
        codes.append(ReasonCode.INVALID_WALL_ID)
    if not is_release_id(release_id):
        codes.append(ReasonCode.INVALID_RELEASE_ID)

    codes.extend(_forbidden_route_files(root))
    codes.extend(_evidence_present(root))

    try:
        manifest = json.loads(cloud_manifest_path(root).read_text(encoding="utf-8"))
        decode_cloud_manifest_candidate(manifest, wall_id=wall_id, release_id=release_id)
    except FileNotFoundError:
        codes.append(ReasonCode.CLOUD_MANIFEST_INVALID)
        manifest = None
    except json.JSONDecodeError:
        codes.append(ReasonCode.CLOUD_MANIFEST_INVALID)
        manifest = None
    except CloudManifestError as exc:
        codes.append(exc.code)
        manifest = None

    if manifest is not None:
        codes.extend(_manifest_matches_package(manifest, package))

    source = package["sourceBuild"]
    identity = _read_json(evidence_path(root, "colmap_source_identity.json"))
    codes.extend(_source_build_gates(root, source, wall_id, identity))
    codes.extend(_asset_bytes(root, package["stage3"]["descriptors"], TYPE_DESCRIPTORS, ReasonCode.DESCRIPTORS_REQUIRED))
    codes.extend(_asset_bytes(root, package["stage3"]["landmarks"], TYPE_LANDMARKS, ReasonCode.LANDMARKS_REQUIRED))
    codes.extend(_asset_bytes(root, package["metricTransform"], TYPE_S_WALL_COLMAP, ReasonCode.METRIC_SIM3_REQUIRED))

    sim3_path = asset_path(root, package["metricTransform"]["assetId"])
    if sim3_path.is_file():
        sim3_codes, sim3_payload = assess_sim3_asset(sim3_path)
        codes.extend(sim3_codes)
        if "error" not in sim3_payload:
            if package["metricTransform"].get("status") != sim3_payload.get("status"):
                codes.append(ReasonCode.SIM3_NOT_VALIDATED)
            fingerprint = None if identity is None else identity.get("modelFingerprint")
            codes.extend(
                assess_sim3_identity(
                    sim3_payload,
                    wall_id=wall_id,
                    model_fingerprint=fingerprint if isinstance(fingerprint, str) else None,
                )
            )

    landmarks_path = asset_path(root, package["stage3"]["landmarks"]["assetId"])
    landmarks = _read_json(landmarks_path)
    if landmarks is None:
        if not any(code in {ReasonCode.LANDMARKS_REQUIRED, ReasonCode.ASSET_HASH_MISMATCH} for code in codes):
            codes.append(ReasonCode.LANDMARKS_REQUIRED)
    else:
        if landmarks.get("wallId") != wall_id:
            codes.append(ReasonCode.WALL_ID_MISMATCH)
        if environment == ENVIRONMENT_PRODUCTION:
            if landmarks.get("developmentFixtureOnly") is True:
                codes.append(ReasonCode.DEVELOPMENT_FIXTURE_NOT_PRODUCTION)
            if landmarks.get("notAWallPackage") is True:
                codes.append(ReasonCode.NOT_A_WALL_PACKAGE_FLAG)

    freeze = _read_json(evidence_path(root, "freeze.json"))
    codes.extend(_stage3_reference_map_binding(package, freeze, identity))
    codes.extend(_freeze_asset_binding(package, freeze))

    if package["capabilities"].get("routeArReady") is True:
        codes.append(ReasonCode.ROUTES_NOT_AUTHORIZED)
    if package.get("routes", {}).get("authorized") is True or package.get("routes", {}).get("present") is True:
        codes.append(ReasonCode.ROUTES_NOT_AUTHORIZED)

    unique = list(dict.fromkeys(codes))
    ready = not unique
    if package["packageState"] == STATE_PACKAGE_READY and not ready:
        unique.append(ReasonCode.DECLARED_STATE_MISMATCH)
        ready = False
    if package["capabilities"].get("localizationReady") is True and not ready:
        if ReasonCode.DECLARED_STATE_MISMATCH not in unique:
            unique.append(ReasonCode.DECLARED_STATE_MISMATCH)
        ready = False

    return PackageValidationResult(
        package_state=STATE_PACKAGE_READY if ready else STATE_NOT_PACKAGE_READY,
        localization_ready=ready,
        route_ar_ready=False,
        reason_codes=[code.value for code in unique],
        wall_id=wall_id,
        release_id=release_id,
        environment=environment,
    )


def _fail(codes: list[ReasonCode]) -> PackageValidationResult:
    unique = list(dict.fromkeys(codes))
    return PackageValidationResult(
        package_state=STATE_NOT_PACKAGE_READY,
        localization_ready=False,
        reason_codes=[code.value for code in unique],
    )


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _forbidden_route_files(root: Path) -> list[ReasonCode]:
    if (root / "routes").exists():
        return [ReasonCode.ROUTES_NOT_AUTHORIZED]
    names: set[str] = set()
    for folder in (root, assets_dir(root), evidence_dir(root)):
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.is_file():
                names.add(path.name)
    if names & FORBIDDEN_ROUTE_NAMES:
        return [ReasonCode.ROUTES_NOT_AUTHORIZED]
    return []


def _evidence_present(root: Path) -> list[ReasonCode]:
    missing = [name for name in required_evidence_names() if not evidence_path(root, name).is_file()]
    return [ReasonCode.MISSING_EVIDENCE] if missing else []


def _source_build_gates(root: Path, source: dict, wall_id: str, identity: dict | None) -> list[ReasonCode]:
    codes: list[ReasonCode] = []
    pq = _read_json(evidence_path(root, "positioning_quality.json"))
    height = _read_json(evidence_path(root, "height_vertical_datum.json"))
    selection = _read_json(evidence_path(root, "stage2_input_selection.json"))
    declared_pq = source.get("positioningQuality") or {}
    declared_height = source.get("heightDatum") or {}
    declared_identity = source.get("colmapSourceIdentity") or {}

    if not isinstance(declared_pq, dict) or not pq:
        codes.append(ReasonCode.POSITIONING_QUALITY_NOT_PASS)
    elif not pq.get("positioningQualityExecutionAllowed") or pq.get("positioningQualityReasonCode") != POSITIONING_FIXED:
        codes.append(ReasonCode.POSITIONING_QUALITY_NOT_PASS)
    elif declared_pq.get("positioningQualityReasonCode") != pq.get("positioningQualityReasonCode"):
        codes.append(ReasonCode.POSITIONING_QUALITY_NOT_PASS)

    if not isinstance(declared_height, dict) or not height:
        codes.append(ReasonCode.HEIGHT_GATE_NOT_PASS)
    elif not height.get("heightGateExecutionAllowed"):
        codes.append(ReasonCode.HEIGHT_GATE_NOT_PASS)
    elif declared_height.get("heightGateExecutionAllowed") != height.get("heightGateExecutionAllowed"):
        codes.append(ReasonCode.HEIGHT_GATE_NOT_PASS)

    if not identity:
        codes.append(ReasonCode.COLMAP_SOURCE_IDENTITY_NOT_PROVEN)
    else:
        if identity.get("wallId") != wall_id:
            codes.append(ReasonCode.WALL_ID_MISMATCH)
        allowed = bool(identity.get("colmapSourceIdentityExecutionAllowed"))
        reason = identity.get("colmapSourceIdentityReasonCode")
        fingerprint = identity.get("modelFingerprint")
        if not allowed or reason != COLMAP_IDENTITY_PROVEN or not isinstance(fingerprint, str) or not fingerprint:
            codes.append(ReasonCode.COLMAP_SOURCE_IDENTITY_NOT_PROVEN)
        declared_fp = declared_identity.get("modelFingerprint")
        if declared_fp != fingerprint:
            codes.append(ReasonCode.COLMAP_SOURCE_IDENTITY_NOT_PROVEN)

    jpeg = source.get("selectedSourceJpegSha256") or {}
    if not jpeg:
        codes.append(ReasonCode.MISSING_EVIDENCE)
    if selection:
        sel_wall = selection.get("wallId")
        if isinstance(sel_wall, str) and sel_wall and sel_wall != wall_id:
            codes.append(ReasonCode.WALL_ID_MISMATCH)
        selected_hashes = selection.get("selectedImageSha256")
        if isinstance(selected_hashes, dict) and selected_hashes and selected_hashes != jpeg:
            codes.append(ReasonCode.MISSING_EVIDENCE)
    return codes


def _asset_bytes(root: Path, spec: dict, expected_type: str, missing: ReasonCode) -> list[ReasonCode]:
    path = asset_path(root, spec["assetId"])
    if not path.is_file():
        return [missing]
    codes: list[ReasonCode] = []
    if spec.get("type") != expected_type:
        codes.append(ReasonCode.ASSET_TYPE_MISMATCH)
    digest = sha256_file(path)
    size = path.stat().st_size
    if digest != spec.get("sha256"):
        codes.append(ReasonCode.ASSET_HASH_MISMATCH)
    if size != spec.get("bytes"):
        codes.append(ReasonCode.ASSET_BYTES_MISMATCH)
    return codes


def _manifest_matches_package(manifest: dict, package: dict) -> list[ReasonCode]:
    by_type = {item["type"]: item for item in manifest["assets"]}
    expected = {
        TYPE_DESCRIPTORS: package["stage3"]["descriptors"],
        TYPE_LANDMARKS: package["stage3"]["landmarks"],
        TYPE_S_WALL_COLMAP: package["metricTransform"],
    }
    codes: list[ReasonCode] = []
    for asset_type, spec in expected.items():
        item = by_type.get(asset_type)
        if item is None:
            codes.append(ReasonCode.MISSING_REQUIRED_ASSET)
            continue
        if item.get("assetId") != spec.get("assetId"):
            codes.append(ReasonCode.CLOUD_MANIFEST_INVALID)
        if item.get("sha256") != spec.get("sha256") or item.get("bytes") != spec.get("bytes"):
            codes.append(ReasonCode.ASSET_HASH_MISMATCH)
    return codes


def _stage3_reference_map_binding(package: dict, freeze: dict | None, identity: dict | None) -> list[ReasonCode]:
    """Fail closed unless freeze.json explicitly binds runId + COLMAP fingerprint.

    Current Gate 3C freeze.json does not contain these fields. Do not infer
    from wallId, directories, timestamps, or filenames.
    """
    declared = package.get("stage3", {}).get("freezeIdentity") or {}
    freeze_fp = None if freeze is None else freeze.get("colmapModelFingerprint")
    freeze_run = None if freeze is None else freeze.get("wallBuildRunId")
    identity_fp = None if identity is None else identity.get("modelFingerprint")
    run_id = package["sourceBuild"]["runId"]
    proven = (
        isinstance(freeze_fp, str)
        and bool(freeze_fp)
        and isinstance(freeze_run, str)
        and bool(freeze_run)
        and isinstance(identity_fp, str)
        and bool(identity_fp)
    )
    if not proven:
        return [ReasonCode.STAGE3_REFERENCE_MAP_BINDING_NOT_PROVEN]
    if freeze_fp != identity_fp or freeze_run != run_id:
        return [ReasonCode.STAGE3_REFERENCE_MAP_BINDING_MISMATCH]
    if declared.get("colmapModelFingerprint") not in (None, freeze_fp):
        return [ReasonCode.STAGE3_REFERENCE_MAP_BINDING_MISMATCH]
    if declared.get("wallBuildRunId") not in (None, freeze_run):
        return [ReasonCode.STAGE3_REFERENCE_MAP_BINDING_MISMATCH]
    return []


def _freeze_asset_binding(package: dict, freeze: dict | None) -> list[ReasonCode]:
    if not freeze:
        return []
    codes: list[ReasonCode] = []
    desc = package["stage3"]["descriptors"]
    land = package["stage3"]["landmarks"]
    if freeze.get("descriptorsSha256") not in (None, desc.get("sha256")):
        codes.append(ReasonCode.ASSET_HASH_MISMATCH)
    if freeze.get("landmarksSha256") not in (None, land.get("sha256")):
        codes.append(ReasonCode.ASSET_HASH_MISMATCH)
    return codes
