"""Model spatial metadata and model-geometry (PLY) candidate handling.

terra_ply / model-export adjacency is PROPOSED_GENERIC_RULE_REQUIRING_VALIDATION.
It is never treated as a frozen/validated METHOD_RULE.
origin_compatible_with_mrk is not used here: it is a spatial sanity check later,
not capture/model provenance proof.
"""

from __future__ import annotations

from .states import (
    APPROVED_SRS,
    PROPOSED_MODEL_TREE_RULE,
    ReasonCode,
    SelectionStatus,
)


def select_model_spatial_metadata(candidates: list[dict]) -> dict:
    legal = [
        item
        for item in candidates
        if item.get("parseable") and item.get("srsOrigin") and not item.get("malformedOrigin")
    ]
    malformed = [item for item in candidates if item.get("malformedOrigin") or (item.get("parseable") and not item.get("srsOrigin"))]
    proposed_notes = [
        {
            "relativePath": item.get("relativePath"),
            "rule": PROPOSED_MODEL_TREE_RULE,
            "usedAsValidatedMethodRule": False,
            "terraPlyAdjacent": (item.get("proposedModelTreeEvidence") or {}).get("terraPlyAdjacent"),
        }
        for item in candidates
    ]

    if not candidates:
        return {
            "status": SelectionStatus.AUTO_FAIL.value,
            "reasonCode": ReasonCode.MODEL_SPATIAL_METADATA_MISSING.value,
            "selected": None,
            "ambiguous": [],
            "proposedRuleNotes": proposed_notes,
        }
    if not legal and malformed:
        return {
            "status": SelectionStatus.AUTO_FAIL.value,
            "reasonCode": ReasonCode.SRSORIGIN_MALFORMED.value,
            "selected": None,
            "ambiguous": [{"relativePath": item["relativePath"]} for item in malformed],
            "proposedRuleNotes": proposed_notes,
        }
    if not legal:
        return {
            "status": SelectionStatus.AUTO_FAIL.value,
            "reasonCode": ReasonCode.MODEL_SPATIAL_METADATA_MALFORMED.value,
            "selected": None,
            "ambiguous": [],
            "proposedRuleNotes": proposed_notes,
        }
    if len(legal) > 1:
        return {
            "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.MODEL_METADATA_ASSOCIATION_RULE_INSUFFICIENT.value,
            "selected": None,
            "ambiguous": [
                {
                    "relativePath": item["relativePath"],
                    "srs": item.get("srs"),
                    "proposedTerraPlyAdjacent": (item.get("proposedModelTreeEvidence") or {}).get(
                        "terraPlyAdjacent"
                    ),
                }
                for item in legal
            ],
            "detail": (
                "Multiple parseable Terra metadata.xml files exist. "
                "terra_ply adjacency is only PROPOSED_GENERIC_RULE_REQUIRING_VALIDATION "
                "and was not used to break the tie. Did not choose first/lexicographic file."
            ),
            "proposedRuleNotes": proposed_notes,
        }

    chosen = legal[0]
    srs = (chosen.get("srs") or "").strip()
    candidate = {
        "relativePath": chosen["relativePath"],
        "filename": chosen["filename"],
        "sha256": chosen.get("sha256"),
        "srs": srs,
        "srsOrigin": chosen.get("srsOrigin"),
        "srsOriginText": chosen.get("srsOriginText"),
        "uniquenessIsNotProvenance": True,
    }
    if srs != APPROVED_SRS:
        return {
            "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.SRS_NOT_EPSG_32650.value,
            "selected": None,
            "uniqueUnprovenCandidate": candidate,
            "ambiguous": [{"relativePath": chosen["relativePath"], "srs": srs}],
            "detail": (
                f"Metadata SRS is {srs!r}; current approved math is {APPROVED_SRS} only. "
                "Do not invent a dynamic UTM zone or new CRS transform."
            ),
            "proposedRuleNotes": proposed_notes,
        }
    return {
        "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
        "reasonCode": ReasonCode.MODEL_GEOMETRY_METADATA_ASSOCIATION_UNPROVEN.value,
        "selected": None,
        "uniqueUnprovenCandidate": candidate,
        "ambiguous": [],
        "detail": (
            "A unique parseable metadata.xml is not proven model↔metadata association. "
            "same model-export tree / terra_ply adjacency is PROPOSED_GENERIC_RULE_REQUIRING_VALIDATION. "
            "Uniqueness, lexicographic order, and origin_compatible_with_mrk are not provenance proof."
        ),
        "proposedRuleNotes": proposed_notes,
    }


def select_ply(candidates: list[dict]) -> dict:
    if not candidates:
        return {
            "status": SelectionStatus.AUTO_FAIL.value,
            "reasonCode": ReasonCode.PLY_MISSING.value,
            "selected": None,
            "ambiguous": [],
        }
    if len(candidates) > 1:
        return {
            "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.PLY_AMBIGUOUS_NO_APPROVED_RULE.value,
            "selected": None,
            "ambiguous": [
                {
                    "relativePath": item["relativePath"],
                    "proposedTerraPlyAdjacent": (item.get("proposedModelTreeEvidence") or {}).get(
                        "terraPlyAdjacent"
                    ),
                }
                for item in candidates
            ],
            "detail": (
                "Multiple PLY files exist. terra_ply adjacency is not a validated METHOD_RULE. "
                "Did not choose first/lexicographic PLY."
            ),
        }
    chosen = candidates[0]
    return {
        "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
        "reasonCode": ReasonCode.MODEL_GEOMETRY_METADATA_ASSOCIATION_UNPROVEN.value,
        "selected": None,
        "uniqueUnprovenCandidate": {
            "relativePath": chosen["relativePath"],
            "filename": chosen["filename"],
            "sha256": chosen.get("sha256"),
            "kind": "modelGeometry",
            "usedInFit": False,
            "uniquenessIsNotProvenance": True,
        },
        "ambiguous": [],
        "detail": (
            "A unique PLY is not proven model-geometry association. "
            "terra_ply adjacency is PROPOSED_GENERIC_RULE_REQUIRING_VALIDATION. "
            "Did not choose by uniqueness, first, or lexicographic order."
        ),
    }


def apply_frozen_identity_regression(
    meta_result: dict,
    ply_result: dict,
    evidence: dict | None,
) -> tuple[dict, dict, bool]:
    """Promote unique unproven candidates only when they match injected frozen identities.

    This is A1/A2 regression evidence. It is not a generic provenance rule and
    must not be keyed on wall_id.
    """
    if not evidence:
        return meta_result, ply_result, False
    meta_path = evidence.get("metadata_xml_relative_path")
    ply_path = evidence.get("ply_relative_path")
    meta_cand = meta_result.get("uniqueUnprovenCandidate")
    ply_cand = ply_result.get("uniqueUnprovenCandidate")
    if not meta_path or not ply_path or not meta_cand or not ply_cand:
        return meta_result, ply_result, False
    if meta_cand.get("relativePath") != meta_path or ply_cand.get("relativePath") != ply_path:
        return meta_result, ply_result, False
    if (meta_cand.get("srs") or "").strip() != APPROVED_SRS or not meta_cand.get("srsOrigin"):
        return meta_result, ply_result, False
    if meta_result.get("reasonCode") != ReasonCode.MODEL_GEOMETRY_METADATA_ASSOCIATION_UNPROVEN.value:
        return meta_result, ply_result, False
    if ply_result.get("reasonCode") != ReasonCode.MODEL_GEOMETRY_METADATA_ASSOCIATION_UNPROVEN.value:
        return meta_result, ply_result, False
    meta_selected = {
        **meta_cand,
        "associationRule": "FROZEN_IDENTITY_REGRESSION_EVIDENCE",
        "uniquenessIsNotProvenance": True,
        "regressionEvidenceNote": (
            "Frozen known identities supplied by the regression caller. "
            "Not a generic model↔metadata provenance rule."
        ),
    }
    ply_selected = {
        **ply_cand,
        "associationRule": "FROZEN_IDENTITY_REGRESSION_EVIDENCE",
        "uniquenessIsNotProvenance": True,
    }
    return (
        {
            **meta_result,
            "status": SelectionStatus.AUTO_PASS.value,
            "reasonCode": ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value,
            "selected": meta_selected,
        },
        {
            **ply_result,
            "status": SelectionStatus.AUTO_PASS.value,
            "reasonCode": ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value,
            "selected": ply_selected,
        },
        True,
    )
