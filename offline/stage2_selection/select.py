"""Machine-explicit Generic Stage 2 input selection."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from offline.ingestion.hashing import sha256_file
from offline.ingestion.pipeline import incoming_dir

from .capture import group_compatible_captures
from .discovery import discover_candidates
from .model import apply_frozen_identity_regression, select_model_spatial_metadata, select_ply
from .mrk import associate_group_to_mrk
from .states import (
    OUTPUT_FRAME,
    SCHEMA_VERSION,
    WALLMETRICMETERS_PROVENANCE,
    ReasonCode,
    SelectionStatus,
    worst_status,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status(value: str) -> SelectionStatus:
    return SelectionStatus(value)


def select_stage2_inputs(
    wall_id: str,
    root: Path,
    *,
    incoming: Path | None = None,
    run_id: str | None = None,
    inventory_source: str = "incoming_scan",
    frozen_identity_regression_evidence: dict | None = None,
) -> dict:
    incoming_wall = incoming or incoming_dir(root, wall_id)
    discovered = discover_candidates(incoming_wall)
    groups, rejected_images = group_compatible_captures(discovered["images"])
    mrk_candidates = discovered["mrkCandidates"]

    group_assoc = []
    selectable = []
    for group in groups:
        assoc = associate_group_to_mrk(group, mrk_candidates)
        row = {**group, "mrkAssociation": assoc}
        group_assoc.append(row)
        if assoc.get("status") == SelectionStatus.AUTO_PASS.value:
            selectable.append(row)

    statuses: list[SelectionStatus] = []
    reason_codes: list[str] = []
    conflicting: list[dict] = []
    ambiguous: list[dict] = []

    selected_capture = None
    selected_mrk = None

    if not groups:
        statuses.append(SelectionStatus.AUTO_FAIL)
        reason_codes.append(ReasonCode.ZERO_COMPATIBLE_PRIMARY_CAPTURE.value)
    elif len(selectable) > 1:
        statuses.append(SelectionStatus.HUMAN_REVIEW_REQUIRED)
        reason_codes.append(ReasonCode.MULTIPLE_SELECTABLE_CAPTURE_GROUPS.value)
        ambiguous.extend({"kind": "captureGroup", "groupId": g["groupId"]} for g in selectable)
    elif len(selectable) == 1:
        selected_capture = {
            "groupId": selectable[0]["groupId"],
            "parentDirectory": selectable[0]["parentDirectory"],
            "filenameDate": selectable[0]["filenameDate"],
            "memberRelativePaths": selectable[0]["memberRelativePaths"],
            "memberCount": selectable[0]["memberCount"],
            "sourceChecksums": {
                m["relativePath"]: m.get("sha256") for m in selectable[0]["members"]
            },
        }
        selected_mrk = selectable[0]["mrkAssociation"]["selected"]
        statuses.append(SelectionStatus.AUTO_PASS)
        reason_codes.append(ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value)
    else:
        assoc_statuses = [_status(g["mrkAssociation"]["status"]) for g in group_assoc]
        worst = worst_status(assoc_statuses)
        statuses.append(worst)
        for group in group_assoc:
            code = group["mrkAssociation"].get("reasonCode")
            if code:
                reason_codes.append(code)
            if group["mrkAssociation"].get("ambiguous"):
                ambiguous.extend(group["mrkAssociation"]["ambiguous"])

    meta_result = select_model_spatial_metadata(discovered["modelSpatialMetadataCandidates"])
    ply_result = select_ply(discovered["modelCandidates"])
    meta_result, ply_result, regression_applied = apply_frozen_identity_regression(
        meta_result,
        ply_result,
        frozen_identity_regression_evidence,
    )
    statuses.append(_status(meta_result["status"]))
    statuses.append(_status(ply_result["status"]))
    if meta_result.get("reasonCode"):
        reason_codes.append(meta_result["reasonCode"])
    if ply_result.get("reasonCode"):
        reason_codes.append(ply_result["reasonCode"])
    if meta_result.get("ambiguous"):
        ambiguous.extend({"kind": "modelSpatialMetadata", **item} for item in meta_result["ambiguous"])
    if ply_result.get("ambiguous"):
        ambiguous.extend({"kind": "modelGeometry", **item} for item in ply_result["ambiguous"])

    selected_meta = meta_result.get("selected")
    selected_srs = selected_meta.get("srs") if selected_meta else None
    selected_origin = selected_meta.get("srsOrigin") if selected_meta else None
    selected_model = ply_result.get("selected")
    unique_unproven_meta = meta_result.get("uniqueUnprovenCandidate")
    unique_unproven_ply = ply_result.get("uniqueUnprovenCandidate")

    if selected_capture and len({Path(p).parent.as_posix() for p in selected_capture["memberRelativePaths"]}) != 1:
        statuses.append(SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED)
        reason_codes.append(ReasonCode.SELECTED_IMAGES_NOT_SINGLE_DIRECTORY.value)
        conflicting.append(
            {
                "kind": "selectedImagesSpanMultipleParents",
                "detail": "Validated pycolmap extract uses a single image_path; splitting is out of this Gate.",
            }
        )

    overall = worst_status(statuses)
    if overall == SelectionStatus.AUTO_PASS:
        reason_codes = [ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value]

    checksums = {}
    for rel in (
        list((selected_capture or {}).get("memberRelativePaths") or [])
        + ([selected_mrk["relativePath"]] if selected_mrk else [])
        + ([selected_meta["relativePath"]] if selected_meta else [])
        + ([selected_model["relativePath"]] if selected_model else [])
        + ([unique_unproven_meta["relativePath"]] if unique_unproven_meta and not selected_meta else [])
        + ([unique_unproven_ply["relativePath"]] if unique_unproven_ply and not selected_model else [])
    ):
        path = incoming_wall / rel
        if path.is_file():
            checksums[rel] = sha256_file(path)

    unique_reasons = []
    for code in reason_codes:
        if code not in unique_reasons:
            unique_reasons.append(code)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "wallId": wall_id,
        "runId": run_id or _now(),
        "generatedAt": _now(),
        "inventorySource": inventory_source,
        "incomingRelative": str(incoming_wall),
        "imageCandidates": [
            {
                "relativePath": img.get("relativePath"),
                "filename": img.get("filename"),
                "role": img.get("role"),
                "colmapSourceCandidate": img.get("colmapSourceCandidate"),
                "cameraMake": img.get("cameraMake"),
            }
            for img in discovered["images"]
        ],
        "captureGroups": [
            {
                "groupId": g["groupId"],
                "parentDirectory": g["parentDirectory"],
                "filenameDate": g["filenameDate"],
                "memberCount": g["memberCount"],
                "memberRelativePaths": g["memberRelativePaths"],
                "groupingKeys": g["groupingKeys"],
                "mrkAssociation": g["mrkAssociation"],
            }
            for g in group_assoc
        ],
        "mrkCandidates": [
            {
                "relativePath": item["relativePath"],
                "parentDirectory": item.get("parentDirectory"),
                "recordCount": item.get("recordCount"),
                "photoIds": item.get("photoIds"),
                "sha256": item.get("sha256"),
            }
            for item in mrk_candidates
        ],
        "captureMetadataCandidates": discovered["captureMetadataCandidates"],
        "modelCandidates": discovered["modelCandidates"],
        "modelSpatialMetadataCandidates": discovered["modelSpatialMetadataCandidates"],
        "atReconstructionMetadataCandidates": discovered["atReconstructionMetadataCandidates"],
        "selectedCapture": selected_capture,
        "selectedMRKSource": selected_mrk,
        "selectedModelSource": selected_model,
        "selectedModelSpatialMetadata": selected_meta,
        "selectedSRS": selected_srs,
        "selectedSRSOrigin": selected_origin,
        "uniqueUnprovenModelSpatialMetadata": unique_unproven_meta if not selected_meta else None,
        "uniqueUnprovenModelGeometry": unique_unproven_ply if not selected_model else None,
        "selectionStatus": overall.value,
        "selectionReasonCodes": unique_reasons,
        "selectionEvidence": {
            "compatiblePrimaryCapture": "DJI originalCameraImage + readable + DJI filename + EXIF make; excludes iPhone/HEIC/texture/tile/report",
            "mrk": "GENERIC_MRK_ASSOCIATION_RULE: photoId identifier + same-parent strong source-group evidence",
            "modelSpatialMetadata": (
                "Uniqueness of metadata.xml or PLY inside incoming/ is not model provenance. "
                "terra_ply adjacency is PROPOSED_GENERIC_RULE_REQUIRING_VALIDATION. "
                "origin_compatible_with_mrk is a spatial sanity check, not provenance."
            ),
            "uniquenessIsNotModelProvenance": True,
            "originCompatibilityIsNotModelProvenance": True,
            "frozenIdentityRegressionEvidenceApplied": regression_applied,
            "crs": "approved math is EPSG:32650 / UTM zone 50 only",
            "outputFrame": OUTPUT_FRAME,
            "originCompatibility": "SPATIAL_SANITY_CHECK later; not used as provenance proof",
            "nearestGpsAuthoritative": False,
            "colmapReadinessNotRequired": True,
            "sessionDji20260823NotRequired": True,
            "expectedImageCountNotRequired": True,
        },
        "rejectedCandidates": {
            "images": rejected_images,
        },
        "ambiguousCandidates": ambiguous,
        "conflictingEvidence": conflicting,
        "sourceChecksums": checksums,
        "provenanceReferences": {
            "incomingImmutable": True,
            "qualificationSessionAuthorizationNotUsed": True,
            "jiulongfengHardcodedPathsNotUsed": True,
        },
        "outputFrame": OUTPUT_FRAME,
        "wallMetricMetersProvenance": WALLMETRICMETERS_PROVENANCE,
        "originCompatibilitySemantics": "SPATIAL_SANITY_CHECK",
        "originCompatibilityIsProvenanceProof": False,
    }
