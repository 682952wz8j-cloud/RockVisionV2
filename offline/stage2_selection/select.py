"""Machine-explicit Generic Stage 2 input selection."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from offline.ingestion.hashing import sha256_file
from offline.ingestion.pipeline import incoming_dir

from .capture import group_compatible_captures
from .discovery import discover_candidates
from .model import apply_frozen_identity_regression
from .mrk import associate_group_to_mrk
from .states import (
    HEIGHT_VERTICAL_DATUM_PROVENANCE,
    OUTPUT_FRAME,
    RULE_C_POLICY,
    SCHEMA_VERSION,
    WALLMETRICMETERS_PROVENANCE,
    ReasonCode,
    SelectionStatus,
    worst_status,
)
from .ellipsoid import evaluate_rule_c_from_selection
from .terra import select_terra_model


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
    frozen_terra_ply_product: dict | None = None,
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

    terra_result = select_terra_model(incoming_wall, frozen_ply_product=frozen_terra_ply_product)
    terra_result, regression_applied = apply_frozen_identity_regression(
        terra_result,
        frozen_identity_regression_evidence,
    )
    statuses.append(_status(terra_result["status"]))
    for code in terra_result.get("reasonCodes") or []:
        reason_codes.append(code)
    if terra_result.get("ambiguous"):
        ambiguous.extend(terra_result["ambiguous"])

    selected_meta = terra_result.get("selectedModelSpatialMetadata")
    selected_srs = selected_meta.get("srs") if selected_meta else None
    selected_origin = selected_meta.get("srsOrigin") if selected_meta else None
    selected_model = terra_result.get("selectedModelSource")
    frame = terra_result.get("terraSpatialFrame")
    if selected_srs is None and frame:
        selected_srs = frame.get("srs")
        selected_origin = frame.get("srsOrigin")

    if selected_capture and len({Path(p).parent.as_posix() for p in selected_capture["memberRelativePaths"]}) != 1:
        statuses.append(SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED)
        reason_codes.append(ReasonCode.SELECTED_IMAGES_NOT_SINGLE_DIRECTORY.value)
        conflicting.append(
            {
                "kind": "selectedImagesSpanMultipleParents",
                "detail": "Validated pycolmap extract uses a single image_path; splitting is out of this Gate.",
            }
        )

    ellipsoid_provenance = evaluate_rule_c_from_selection(
        incoming_wall,
        selected_capture=selected_capture,
        selected_mrk=selected_mrk,
        mrk_candidates=mrk_candidates,
        terra_result=terra_result,
        discovered_images=discovered["images"],
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
        + [
            item["relativePath"]
            for item in terra_result.get("terraMetadataCopies") or []
            if item.get("relativePath")
        ]
    ):
        path = incoming_wall / rel
        if path.is_file():
            checksums[rel] = sha256_file(path)

    unique_reasons = []
    for code in reason_codes:
        if code not in unique_reasons:
            unique_reasons.append(code)
    if overall != SelectionStatus.AUTO_PASS:
        unique_reasons = [
            code for code in unique_reasons if code != ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value
        ]

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
        "modelCandidates": terra_result.get("modelCandidates") or [],
        "modelSpatialMetadataCandidates": terra_result.get("modelSpatialMetadataCandidates") or [],
        "atReconstructionMetadataCandidates": discovered["atReconstructionMetadataCandidates"],
        "terraExportRoot": terra_result.get("terraExportRoot"),
        "terraExportRootEvidence": terra_result.get("terraExportRootEvidence"),
        "terraSpatialFrame": terra_result.get("terraSpatialFrame"),
        "terraMetadataCopies": terra_result.get("terraMetadataCopies") or [],
        "terraProducts": terra_result.get("terraProducts") or [],
        "intermediateCandidates": terra_result.get("intermediateCandidates") or [],
        "terraPlyProduct": terra_result.get("terraPlyProduct"),
        "selectedCapture": selected_capture,
        "selectedMRKSource": selected_mrk,
        "selectedModelSource": selected_model if overall == SelectionStatus.AUTO_PASS else None,
        "selectedModelSpatialMetadata": selected_meta if overall == SelectionStatus.AUTO_PASS else None,
        "selectedCrosscheckProduct": terra_result.get("selectedCrosscheckProduct")
        if overall == SelectionStatus.AUTO_PASS
        else None,
        "selectedCrosscheckGeometry": terra_result.get("selectedCrosscheckGeometry")
        if overall == SelectionStatus.AUTO_PASS
        else None,
        "selectedSRS": selected_srs if overall == SelectionStatus.AUTO_PASS else None,
        "selectedSRSOrigin": selected_origin if overall == SelectionStatus.AUTO_PASS else None,
        "uniqueUnprovenModelSpatialMetadata": terra_result.get("uniqueUnprovenModelSpatialMetadata"),
        "uniqueUnprovenModelGeometry": terra_result.get("uniqueUnprovenModelGeometry"),
        "selectionStatus": overall.value,
        "selectionReasonCodes": unique_reasons,
        "selectionEvidence": {
            "compatiblePrimaryCapture": "DJI originalCameraImage + readable + DJI filename + EXIF make; excludes iPhone/HEIC/texture/tile/report",
            "mrk": "GENERIC_MRK_ASSOCIATION_RULE: photoId identifier + same-parent strong source-group evidence",
            "terraExportRoot": "APPROVED_METHOD_RULE: directory with a direct child named terra_*, not under .temp; name 0 is not required",
            "terraSpatialFrame": "APPROVED_METHOD_RULE: agreeing ModelMetadata SRS + parsed SRSOrigin; copies are frame copies, not geometry pointers",
            "terraPlyProduct": (
                "APPROVED_METHOD_RULE: formal reconstruction PLY is the unique usable "
                "geometry under a Terra product declared by model_report.json "
                "(generate point ply → terra_point_ply, generate ply → terra_ply). "
                ".temp intermediates are never formal products. "
                "No model_report falls back to a unique terra_ply/terra_point_ply "
                "directory that already contains usable geometry. "
                "Filesystem order, mtime, and size are not selection keys."
            ),
            "modelSpatialMetadata": (
                "Uniqueness of metadata.xml or PLY is not model provenance. "
                "Geometry is not spatial-frame provenance. "
                "origin_compatible_with_mrk is a spatial sanity check, not provenance."
            ),
            "uniquenessIsNotModelProvenance": True,
            "originCompatibilityIsNotModelProvenance": True,
            "geometryIsNotFrameProvenance": True,
            "frozenIdentityRegressionEvidenceApplied": regression_applied,
            "crs": "approved math is EPSG:32650 / UTM zone 50 only",
            "outputFrame": OUTPUT_FRAME,
            "originCompatibility": "SPATIAL_SANITY_CHECK later; not used as provenance proof",
            "nearestGpsAuthoritative": False,
            "colmapReadinessNotRequired": True,
            "sessionDji20260823NotRequired": True,
            "expectedImageCountNotRequired": True,
            "heightVerticalDatumProvenance": HEIGHT_VERTICAL_DATUM_PROVENANCE,
            "ruleCPolicy": RULE_C_POLICY,
            "gpsMapDatumIsNotProvenWgs84": True,
            "epsg32650IsNotCaptureEllipsoidProof": True,
            "rtkDiffAgeIsNotRtkSource": True,
            "mrkQIsNotRtkSource": True,
            "numericalSanityIsNotDatumProvenance": True,
            "plyUsedInFit": False,
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
            "wallIdNotUsedForTerraProvenance": True,
            "humanFolderNamesNotUsedForTerraProvenance": True,
        },
        "outputFrame": OUTPUT_FRAME,
        "wallMetricMetersProvenance": WALLMETRICMETERS_PROVENANCE,
        "heightVerticalDatumProvenance": HEIGHT_VERTICAL_DATUM_PROVENANCE,
        "gnssReferenceEllipsoidProvenance": ellipsoid_provenance,
        "originCompatibilitySemantics": "SPATIAL_SANITY_CHECK",
        "originCompatibilityIsProvenanceProof": False,
    }
