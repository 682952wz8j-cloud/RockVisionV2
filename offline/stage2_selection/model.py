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
    if srs != APPROVED_SRS:
        return {
            "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.SRS_NOT_EPSG_32650.value,
            "selected": None,
            "ambiguous": [{"relativePath": chosen["relativePath"], "srs": srs}],
            "detail": (
                f"Selected metadata SRS is {srs!r}; current approved math is {APPROVED_SRS} only. "
                "Do not invent a dynamic UTM zone or new CRS transform."
            ),
            "proposedRuleNotes": proposed_notes,
        }
    return {
        "status": SelectionStatus.AUTO_PASS.value,
        "reasonCode": ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value,
        "selected": {
            "relativePath": chosen["relativePath"],
            "filename": chosen["filename"],
            "sha256": chosen.get("sha256"),
            "srs": srs,
            "srsOrigin": chosen.get("srsOrigin"),
            "srsOriginText": chosen.get("srsOriginText"),
            "associationRule": "unique_parseable_terra_metadata_xml",
            "regressionEvidenceNote": (
                "A Jiulongfeng hard-coded metadata.xml path is regression evidence only, "
                "not a generic method rule."
            ),
        },
        "ambiguous": [],
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
        "status": SelectionStatus.AUTO_PASS.value,
        "reasonCode": ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value,
        "selected": {
            "relativePath": chosen["relativePath"],
            "filename": chosen["filename"],
            "sha256": chosen.get("sha256"),
            "kind": "modelGeometry",
            "usedInFit": False,
        },
        "ambiguous": [],
    }
