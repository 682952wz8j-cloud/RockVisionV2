"""Positioning-quality Policy v1 — Generic Stage 2 admission.

Authoritative token: JPEG XMP RtkFlag.
Does not substitute MRK Q, GpsStatus, AltitudeType, SurveyingMode,
RtkStd*, RtkDiffAge, Sim(3) residuals, or wall identity.

Does not implement frame filtering, percentage/min-count/coverage
thresholds, or a Tier-2 non-fixed contract.

This module does not estimate Sim(3) or change frozen registration math.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from offline.qualification.associate import dji_filename_parts
from offline.stage2_selection.ellipsoid import extract_jpeg_xmp_text, xmp_attr_occurrences

POSITIONING_QUALITY_POLICY_VERSION = "POSITIONING_QUALITY_POLICY_V1"
POSITIONING_QUALITY_GATE_IMPLEMENTATION_IMPLEMENTED = True
POSITIONING_QUALITY_GATE_PASS = False
TIER_2_ENABLED = False

REASON_FIXED = "POSITIONING_QUALITY_FIXED"
REASON_NOT_SUPPORTED = "POSITIONING_QUALITY_NOT_SUPPORTED"
REASON_NOT_PROVEN = "POSITIONING_QUALITY_NOT_PROVEN"
REASON_CONFLICT = "POSITIONING_QUALITY_CONFLICT"

CLASS_FIXED = "TIER_1_FIXED"
CLASS_NOT_SUPPORTED = "NOT_POSITIONING_QUALITY_ELIGIBLE"
CLASS_NOT_PROVEN = "POSITIONING_QUALITY_NOT_PROVEN"
CLASS_CONFLICT = "POSITIONING_QUALITY_CONFLICT"

_INT_RE = re.compile(r"^[+-]?\d+$")
_REASON_PRECEDENCE = (
    REASON_CONFLICT,
    REASON_NOT_PROVEN,
    REASON_NOT_SUPPORTED,
    REASON_FIXED,
)


def _parse_rtk_flag_token(raw: str) -> tuple[str, int | None]:
    text = str(raw).strip()
    if text == "":
        return "EMPTY", None
    if not _INT_RE.fullmatch(text):
        return "UNPARSEABLE", None
    return "INT", int(text)


def classify_rtk_flag_occurrences(occurrences: list[str] | None) -> dict:
    values = list(occurrences or [])
    if not values:
        return {
            "classification": CLASS_NOT_PROVEN,
            "reasonCode": REASON_NOT_PROVEN,
            "eligible": False,
            "rtkFlag": None,
            "rtkFlagRaw": None,
            "distributionKey": "MISSING",
        }

    parsed: list[tuple[str, int | None, str]] = []
    for raw in values:
        kind, number = _parse_rtk_flag_token(raw)
        parsed.append((kind, number, raw))

    ints = [number for kind, number, _raw in parsed if kind == "INT" and number is not None]
    unique_ints = sorted(set(ints))
    has_unparseable = any(kind == "UNPARSEABLE" for kind, _n, _raw in parsed)
    has_empty = any(kind == "EMPTY" for kind, _n, _raw in parsed)

    if len(unique_ints) > 1:
        return {
            "classification": CLASS_CONFLICT,
            "reasonCode": REASON_CONFLICT,
            "eligible": False,
            "rtkFlag": None,
            "rtkFlagRaw": values[0] if len(values) == 1 else values,
            "distributionKey": "CONFLICT",
        }
    if unique_ints and (has_unparseable or (has_empty and len(values) > 1)):
        return {
            "classification": CLASS_CONFLICT,
            "reasonCode": REASON_CONFLICT,
            "eligible": False,
            "rtkFlag": unique_ints[0],
            "rtkFlagRaw": values[0] if len(values) == 1 else values,
            "distributionKey": "CONFLICT",
        }
    if not unique_ints:
        return {
            "classification": CLASS_NOT_PROVEN,
            "reasonCode": REASON_NOT_PROVEN,
            "eligible": False,
            "rtkFlag": None,
            "rtkFlagRaw": values[0] if len(values) == 1 else values,
            "distributionKey": "UNPARSEABLE" if has_unparseable else "EMPTY",
        }

    flag = unique_ints[0]
    raw_one = values[0] if len(values) == 1 else values
    if flag == 50:
        return {
            "classification": CLASS_FIXED,
            "reasonCode": REASON_FIXED,
            "eligible": True,
            "rtkFlag": 50,
            "rtkFlagRaw": raw_one,
            "distributionKey": "50",
        }
    return {
        "classification": CLASS_NOT_SUPPORTED,
        "reasonCode": REASON_NOT_SUPPORTED,
        "eligible": False,
        "rtkFlag": flag,
        "rtkFlagRaw": raw_one,
        "distributionKey": str(flag),
    }


def collect_positioning_quality_frames(incoming: Path, image_relative_paths: tuple[str, ...] | list[str]) -> list[dict]:
    """Read XMP RtkFlag for each selected capture frame. No filtering."""
    frames: list[dict] = []
    for rel in list(image_relative_paths):
        path = incoming / rel
        parts = dji_filename_parts(Path(rel).name)
        sequence = parts["sequence"] if parts else None
        if not path.is_file():
            frames.append(
                {
                    "imageRelativePath": rel,
                    "sequence": sequence,
                    "rtkFlagOccurrences": [],
                    "xmpPresent": False,
                    "sourceAvailable": False,
                }
            )
            continue
        text = extract_jpeg_xmp_text(path)
        frames.append(
            {
                "imageRelativePath": rel,
                "sequence": sequence,
                "rtkFlagOccurrences": xmp_attr_occurrences(text, "RtkFlag"),
                "xmpPresent": text is not None,
                "sourceAvailable": True,
            }
        )
    return frames


def evaluate_positioning_quality_v1(frames: list[dict] | tuple[dict, ...] | None) -> dict:
    """Session Policy v1: every selected frame must be RtkFlag=50. No frame filtering."""
    selected = [dict(item) for item in (frames or [])]
    classified = []
    for item in selected:
        occurrences = item.get("rtkFlagOccurrences")
        if occurrences is None and "rtkFlagRaw" in item:
            raw = item.get("rtkFlagRaw")
            if raw is None:
                occurrences = []
            elif isinstance(raw, list):
                occurrences = list(raw)
            else:
                occurrences = [str(raw)]
        classified_one = classify_rtk_flag_occurrences(occurrences)
        row = {
            "imageRelativePath": item.get("imageRelativePath"),
            "sequence": item.get("sequence"),
            "classification": classified_one["classification"],
            "reasonCode": classified_one["reasonCode"],
            "positioningQualityEligible": classified_one["eligible"],
            "rtkFlag": classified_one["rtkFlag"],
            "rtkFlagRaw": classified_one["rtkFlagRaw"],
            "distributionKey": classified_one["distributionKey"],
        }
        classified.append(row)

    counts = Counter(row["reasonCode"] for row in classified)
    dist = Counter(row["distributionKey"] for row in classified)
    if not classified:
        session_reason = REASON_NOT_PROVEN
    else:
        present = {row["reasonCode"] for row in classified}
        session_reason = REASON_FIXED
        for reason in _REASON_PRECEDENCE:
            if reason in present:
                session_reason = reason
                break

    allowed = session_reason == REASON_FIXED and bool(classified)
    if session_reason == REASON_FIXED:
        provenance = "AUTO_PASS"
    elif session_reason == REASON_CONFLICT:
        provenance = "HUMAN_REVIEW_REQUIRED"
    else:
        provenance = "DEVELOPMENT_GATE_REVIEW_REQUIRED"

    blocking = sorted(
        (
            {
                "imageRelativePath": row["imageRelativePath"],
                "sequence": row["sequence"],
                "rtkFlag": row["rtkFlag"],
                "classification": row["classification"],
                "reasonCode": row["reasonCode"],
            }
            for row in classified
            if row["reasonCode"] == session_reason and session_reason != REASON_FIXED
        ),
        key=lambda row: (str(row["imageRelativePath"] or ""), row["sequence"] if row["sequence"] is not None else -1),
    )
    frames_out = sorted(
        classified,
        key=lambda row: (str(row["imageRelativePath"] or ""), row["sequence"] if row["sequence"] is not None else -1),
    )
    dist_out = [
        {"value": key, "count": dist[key]}
        for key in sorted(dist.keys(), key=lambda item: (item not in {"MISSING", "EMPTY", "UNPARSEABLE", "CONFLICT"}, item))
    ]

    return {
        "policyVersion": POSITIONING_QUALITY_POLICY_VERSION,
        "tier2Enabled": TIER_2_ENABLED,
        "selectedFrameCount": len(classified),
        "fixedFrameCount": sum(1 for row in classified if row["reasonCode"] == REASON_FIXED),
        "nonFixedFrameCount": sum(1 for row in classified if row["reasonCode"] == REASON_NOT_SUPPORTED),
        "missingOrUnparseableFrameCount": sum(1 for row in classified if row["reasonCode"] == REASON_NOT_PROVEN),
        "conflictFrameCount": sum(1 for row in classified if row["reasonCode"] == REASON_CONFLICT),
        "rtkFlagDistribution": dist_out,
        "positioningQualityProvenance": provenance,
        "positioningQualityReasonCode": session_reason,
        "positioningQualityExecutionAllowed": allowed,
        "positioningQualityGatePass": False,
        "productionBuildStage2Enabled": False,
        "genericStage2Pass": False,
        "blockingFrames": blocking,
        "frames": frames_out,
        "reasonCounts": {reason: int(counts.get(reason, 0)) for reason in _REASON_PRECEDENCE},
    }


def evaluate_positioning_quality_from_sources(incoming: Path, sources) -> dict:
    injected = getattr(sources, "positioning_quality_frames", None)
    if injected is not None:
        frames = list(injected)
    else:
        frames = collect_positioning_quality_frames(incoming, getattr(sources, "image_relative_paths", ()) or ())
    return evaluate_positioning_quality_v1(frames)
