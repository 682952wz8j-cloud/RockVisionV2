"""MRK association evidence.

FROZEN_JIULONGFENG_ASSOCIATION_RULE = same_parent + filename sequence == photoId
GENERIC_MRK_ASSOCIATION_RULE:
  filename sequence == MRK.photoId is identifier evidence
  same-parent is strong source-group evidence
  non-same-parent must not be guessed and must not AUTO_FAIL merely because parent differs

Nearest GPS is never authoritative.
"""

from __future__ import annotations

from pathlib import Path

from .states import (
    FROZEN_JIULONGFENG_ASSOCIATION_RULE,
    GENERIC_MRK_ASSOCIATION_RULE,
    ReasonCode,
    SelectionStatus,
)


def _parent(rel: str) -> str:
    parent = Path(rel).parent.as_posix()
    return parent if parent != "." else "."


def _photo_id_set(mrk: dict) -> set[int]:
    return {pid for pid in mrk.get("photoIds") or [] if isinstance(pid, int)}


def associate_group_to_mrk(group: dict, mrk_candidates: list[dict]) -> dict:
    sequences = [m.get("filenameSequence") for m in group.get("members") or []]
    if not sequences or any(seq is None for seq in sequences):
        return {
            "status": SelectionStatus.AUTO_FAIL.value,
            "reasonCode": ReasonCode.MRK_MISSING.value,
            "selected": None,
            "ambiguous": [],
            "evidence": ["Compatible capture members lack DJI filename sequences."],
            "nearestGpsAuthoritative": False,
        }
    needed = set(sequences)
    parent = group.get("parentDirectory") or "."

    same_parent = [mrk for mrk in mrk_candidates if mrk.get("parentDirectory") == parent]
    covering = [mrk for mrk in same_parent if needed <= _photo_id_set(mrk)]

    evidence = [
        "identifierEvidence=filename_sequence==MRK.photoId",
        "sameParent=strong_source_group_evidence_not_universal_fail_rule",
        "nearestGpsAuthoritative=false",
        f"neededPhotoIds={sorted(needed)}",
        f"sameParentMrkCount={len(same_parent)}",
        f"sameParentCoveringCount={len(covering)}",
    ]

    if len(covering) == 1:
        mrk = covering[0]
        return {
            "status": SelectionStatus.AUTO_PASS.value,
            "reasonCode": ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value,
            "selected": {
                "relativePath": mrk["relativePath"],
                "filename": mrk["filename"],
                "sha256": mrk.get("sha256"),
                "parentDirectory": mrk.get("parentDirectory"),
                "associationMethod": "filename_sequence==MRK.photoId + same_parent_directory",
                "associationRule": GENERIC_MRK_ASSOCIATION_RULE,
                "frozenJiulongfengRuleAlsoHolds": True,
                "frozenRuleName": FROZEN_JIULONGFENG_ASSOCIATION_RULE,
                "identifierEvidence": "filename_sequence==MRK.photoId",
                "sourceGroupEvidence": "same_parent_directory",
                "recordCount": mrk.get("recordCount"),
                "photoIds": mrk.get("photoIds"),
            },
            "ambiguous": [],
            "evidence": evidence
            + [
                f"unique same-parent MRK {mrk['relativePath']} covers every selected photoId",
            ],
            "nearestGpsAuthoritative": False,
        }

    if len(covering) > 1:
        return {
            "status": SelectionStatus.HUMAN_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.MRK_AMBIGUOUS.value,
            "selected": None,
            "ambiguous": [
                {"relativePath": mrk["relativePath"], "sha256": mrk.get("sha256")}
                for mrk in covering
            ],
            "evidence": evidence
            + ["Approved same-parent+photoId rule matches more than one legal MRK."],
            "nearestGpsAuthoritative": False,
        }

    other_covering = [
        mrk
        for mrk in mrk_candidates
        if mrk.get("parentDirectory") != parent and needed <= _photo_id_set(mrk)
    ]
    if other_covering:
        return {
            "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.MRK_NON_SAME_PARENT_INSUFFICIENT_EVIDENCE.value,
            "selected": None,
            "ambiguous": [
                {"relativePath": mrk["relativePath"], "parentDirectory": mrk.get("parentDirectory")}
                for mrk in other_covering
            ],
            "evidence": evidence
            + [
                "Non-same-parent MRK files share photoId identifier evidence.",
                "Approved source-group evidence is insufficient to uniquely prove association.",
                "Did not guess, did not use nearest GPS, did not pick first/lexicographic MRK.",
                "Non-same-parent is not AUTO_FAIL.",
            ],
            "nearestGpsAuthoritative": False,
        }

    if not mrk_candidates:
        return {
            "status": SelectionStatus.AUTO_FAIL.value,
            "reasonCode": ReasonCode.MRK_MISSING.value,
            "selected": None,
            "ambiguous": [],
            "evidence": evidence + ["No MRK files discovered."],
            "nearestGpsAuthoritative": False,
        }

    return {
        "status": SelectionStatus.AUTO_FAIL.value,
        "reasonCode": ReasonCode.MRK_MISSING.value,
        "selected": None,
        "ambiguous": [],
        "evidence": evidence
        + ["No MRK covers the selected photoIds (missing required MRK evidence)."],
        "nearestGpsAuthoritative": False,
    }
