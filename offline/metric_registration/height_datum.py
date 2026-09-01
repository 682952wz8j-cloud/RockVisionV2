"""Height-datum contracts and generic provenance enforcement.

Frozen WallLocal math is not implemented here:
    Z = Ellh - SRSOrigin.Z
is a same-frame translation in frames.to_wall_local.

This module decides whether generic metric-registration may continue.
It does not convert datums, apply geoid/EGM offsets, or estimate Sim(3).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from offline.qualification.geodesy import geographic_to_utm
from offline.qualification.rtk import parse_mrk
from offline.stage2_capability import capability_fields

from .frames import UTM_EPSG, geodetic_to_projected_metric

SFM_GEO_DESC = "九龙峰森林站大楼/AT/sfm_geo_desc.json"
LEGACY_MRK = "dji_flight_raw_jiulongfeng/rtk_ppk_004/DJI_20260812152955_0002_D.MRK"

HEIGHT_VERTICAL_DATUM_ENFORCEMENT_IMPLEMENTED = True
VERTICAL_OVERRIDE_ABSENCE_CORRECTION_IMPLEMENTED = True
MULTIPLE_OVERRIDE_DESCRIPTOR_CORRECTION_IMPLEMENTED = True
VERTICAL_OVERRIDE_CONFLICT_PRECEDENCE_CORRECTION_IMPLEMENTED = True

# Same tokens as offline.stage2_selection.ellipsoid. Not a second vocabulary.
FIELD_NOT_PRESENT = "FIELD_NOT_PRESENT"
FIELD_PRESENT_EMPTY = "FIELD_PRESENT_EMPTY"
FIELD_PRESENT_POPULATED = "FIELD_PRESENT_POPULATED"
FIELD_CONFLICT = "FIELD_CONFLICT"
EVIDENCE_NOT_AVAILABLE = "EVIDENCE_NOT_AVAILABLE"

_OVERRIDE_ABSENCE_STATES = frozenset({FIELD_NOT_PRESENT, FIELD_PRESENT_EMPTY})
_OVERRIDE_KNOWN_STATES = frozenset(
    {
        FIELD_NOT_PRESENT,
        FIELD_PRESENT_EMPTY,
        FIELD_PRESENT_POPULATED,
        FIELD_CONFLICT,
        EVIDENCE_NOT_AVAILABLE,
    }
)

APPROVED_ELLIPSOID_STATUSES = frozenset(
    {
        "PROVEN_WGS84",
        "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC",
    }
)
APPROVED_ELLIPSOIDAL_SEMANTICS = frozenset(
    {
        "ELLIPSOIDAL",
        "ellipsoidal",
        "GEODETIC_ELLIPSOIDAL_HEIGHT",
        "GNSS_GEODETIC_ELLIPSOIDAL_HEIGHT",
    }
)
CONTRADICTED_HEIGHT_SEMANTICS = frozenset(
    {
        "ORTHOMETRIC",
        "orthometric",
        "MSL",
        "GEOID",
        "geoid",
    }
)

REASON_HEIGHT_APPROVED = "HEIGHT_VERTICAL_DATUM_PROVENANCE_APPROVED"
REASON_ELLIPSOID_NOT_PROVEN = "REFERENCE_ELLIPSOID_NOT_PROVEN"
REASON_NON_WGS84_UNSUPPORTED = "NON_WGS84_REFERENCE_NOT_SUPPORTED"
REASON_ELLIPSOID_CONFLICT = "REFERENCE_ELLIPSOID_CONFLICT"
REASON_MRK_ELLH_NOT_PROVEN = "MRK_ELLH_NOT_PROVEN"
REASON_MRK_SEMANTIC_CONTRADICTION = "MRK_VERTICAL_SEMANTIC_CONTRADICTION"
REASON_TERRA_VERTICAL_NOT_PROVEN = "TERRA_VERTICAL_MODE_NOT_PROVEN"
REASON_TERRA_VERTICAL_UNSUPPORTED = "TERRA_VERTICAL_MODE_NOT_SUPPORTED"
REASON_GEOID_UNSUPPORTED = "GEOID_CONVERSION_NOT_SUPPORTED"
REASON_GEOID_NOT_PROVEN = "GEOID_CONFIGURATION_NOT_PROVEN"
REASON_OVERRIDE_UNSUPPORTED = "VERTICAL_OVERRIDE_NOT_SUPPORTED"
REASON_OVERRIDE_NOT_PROVEN = "VERTICAL_OVERRIDE_STATE_NOT_PROVEN"
REASON_OVERRIDE_CONFLICT = "VERTICAL_OVERRIDE_CONFLICT"
REASON_INVALID_ORIGIN = "INVALID_SRS_ORIGIN"
REASON_ORIGIN_MISMATCH = "SRSORIGIN_PROVENANCE_MISMATCH"
REASON_EVIDENCE_NOT_PROVIDED = "HEIGHT_PROVENANCE_EVIDENCE_NOT_PROVIDED"


def generic_height_contract(origin: list[float]) -> dict:
    """Describes the approved Z operation. Not a provenance PASS."""
    return {
        "heightDatumUsed": "ellipsoidal",
        "srsOrigin": origin,
        "genericContract": "WallLocal Z = Ellh - Origin_H",
        "wallLocalZOperation": "ELLH_MINUS_SRSORIGIN_Z",
        "legacyProofRequired": False,
        "mixedDatumDetected": False,
        "problems": [],
        "noGeoidOffsetApplied": True,
        "originCompatibilityIsProvenanceProof": False,
        "note": (
            "Generic new walls use selected capture MRK Ellh and selected model SRSOrigin. "
            "origin_compatible_with_mrk is a spatial sanity check, not capture/model provenance. "
            "This contract is not a height-gate PASS; evaluate_generic_height_provenance decides."
        ),
    }


def vertical_override_field_state_from_terra_evidence(terra_evidence: list | None) -> str | None:
    rows = [item for item in (terra_evidence or []) if item.get("field") == "override_vertical_cs"]
    if not rows:
        return None
    states = [item.get("fieldState") for item in rows]
    if any(state == FIELD_CONFLICT for state in states):
        return FIELD_CONFLICT
    if any(state not in _OVERRIDE_KNOWN_STATES for state in states):
        return EVIDENCE_NOT_AVAILABLE
    unique = set(states)
    if len(unique) == 1:
        return states[0]
    if FIELD_PRESENT_POPULATED in unique and (unique & _OVERRIDE_ABSENCE_STATES):
        return FIELD_CONFLICT
    return EVIDENCE_NOT_AVAILABLE


def vertical_override_state_from_terra_evidence(terra_evidence: list | None) -> str:
    """NO / YES / UNKNOWN from explicit fieldState. No rawValue-only inference."""
    rows = [item for item in (terra_evidence or []) if item.get("field") == "override_vertical_cs"]
    if not rows:
        return "UNKNOWN"
    states = []
    for row in rows:
        state = row.get("fieldState")
        if state not in _OVERRIDE_KNOWN_STATES:
            states.append(EVIDENCE_NOT_AVAILABLE)
        else:
            states.append(state)
    if any(state == FIELD_CONFLICT for state in states):
        return "UNKNOWN"
    has_populated = any(state == FIELD_PRESENT_POPULATED for state in states)
    has_absence = any(state in _OVERRIDE_ABSENCE_STATES for state in states)
    has_unavailable = any(state == EVIDENCE_NOT_AVAILABLE for state in states)
    if has_populated and (has_absence or has_unavailable):
        return "UNKNOWN"
    if has_populated:
        return "YES"
    if has_unavailable:
        return "UNKNOWN"
    if has_absence:
        return "NO"
    return "UNKNOWN"


def height_evidence_from_rule_c_payload(
    rule_c: dict | None,
    *,
    selected_srs_origin,
    selected_metadata_relative_path: str | None,
    terra_export_root_relative: str | None = None,
) -> dict:
    """Project already-derived Rule C + Terra selection fields into gate inputs."""
    payload = rule_c or {}
    mrk = payload.get("mrkEllh") or {}
    return {
        "referenceEllipsoid": payload.get("referenceEllipsoid"),
        "referenceEllipsoidProvenanceStatus": payload.get("referenceEllipsoidProvenanceStatus"),
        "specDefaultInvoked": payload.get("specDefaultInvoked"),
        "mrkEllhValid": mrk.get("valid"),
        "heightObservationSemantic": payload.get("heightObservationSemantic"),
        "terraVerticalMode": payload.get("terraVerticalMode"),
        "geoidConversionConfigured": payload.get("geoidConversionConfigured"),
        "verticalOverrideConfigured": vertical_override_state_from_terra_evidence(
            payload.get("terraVerticalEvidence")
        ),
        "verticalOverrideFieldState": vertical_override_field_state_from_terra_evidence(
            payload.get("terraVerticalEvidence")
        ),
        "selectedSrsOrigin": list(selected_srs_origin) if selected_srs_origin is not None else None,
        "selectedMetadataRelativePath": selected_metadata_relative_path,
        "terraExportRootRelative": terra_export_root_relative,
        "ruleCConsumed": True,
        "ruleCPolicy": payload.get("policy"),
    }


def _finite_origin(origin) -> list[float] | None:
    if not isinstance(origin, (list, tuple)) or len(origin) != 3:
        return None
    try:
        values = [float(part) for part in origin]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    return values


def _origins_equal(left, right) -> bool:
    a = _finite_origin(left)
    b = _finite_origin(right)
    if a is None or b is None:
        return False
    return a == b


def _metadata_belongs_to_selected_frame(
    *,
    used_path: str | None,
    selected_path: str | None,
    export_root: str | None,
) -> bool:
    if not used_path or not selected_path:
        return False
    if used_path != selected_path:
        return False
    if not export_root:
        return True
    root = str(export_root).rstrip("/")
    return used_path == root or used_path.startswith(root + "/")


def _base_result(
    *,
    provenance: str,
    reason: str,
    allowed: bool,
    mixed,
    origin,
    evidence: dict,
    extra: dict | None = None,
) -> dict:
    payload = {
        "HEIGHT_VERTICAL_DATUM_ENFORCEMENT_IMPLEMENTED": HEIGHT_VERTICAL_DATUM_ENFORCEMENT_IMPLEMENTED,
        "heightVerticalDatumProvenance": provenance,
        "heightGateExecutionAllowed": allowed,
        "reasonCode": reason,
        "mixedDatumDetected": mixed,
        "legacyProofRequired": False,
        "originCompatibilityIsProvenanceProof": False,
        "numericSanityIsNotDatumProvenance": True,
        "wallIdIgnored": True,
        "sim3MetricsIgnored": True,
        "sameVerticalFrame": True if allowed else None,
        "heightDatumUsed": "ELLIPSOIDAL" if allowed else None,
        "referenceEllipsoid": evidence.get("referenceEllipsoid"),
        "referenceEllipsoidProvenanceStatus": evidence.get("referenceEllipsoidProvenanceStatus"),
        "specDefaultInvoked": evidence.get("specDefaultInvoked"),
        "mrkEllhValid": evidence.get("mrkEllhValid"),
        "heightObservationSemantic": evidence.get("heightObservationSemantic"),
        "terraVerticalMode": evidence.get("terraVerticalMode"),
        "geoidConversionConfigured": evidence.get("geoidConversionConfigured"),
        "verticalOverrideConfigured": evidence.get("verticalOverrideConfigured"),
        "verticalOverrideFieldState": evidence.get("verticalOverrideFieldState"),
        "wallLocalZOperation": "ELLH_MINUS_SRSORIGIN_Z" if allowed else None,
        "noGeoidOffsetApplied": True if allowed else None,
        "srsOrigin": origin,
        "genericContract": "WallLocal Z = Ellh - Origin_H" if allowed else None,
        "problems": [] if allowed else [reason],
        **capability_fields(),
    }
    if extra:
        payload.update(extra)
    return payload


def evaluate_generic_height_provenance(evidence: dict | None) -> dict:
    """Deterministic generic height gate. Consumes already-derived evidence only."""
    if not evidence:
        return _base_result(
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_EVIDENCE_NOT_PROVIDED,
            allowed=False,
            mixed=False,
            origin=None,
            evidence={},
        )

    used_origin = evidence.get("usedSrsOrigin", evidence.get("srsOrigin"))
    selected_origin = evidence.get("selectedSrsOrigin")
    parsed_used = _finite_origin(used_origin)
    if parsed_used is None:
        return _base_result(
            provenance="AUTO_FAIL",
            reason=REASON_INVALID_ORIGIN,
            allowed=False,
            mixed=False,
            origin=used_origin,
            evidence=evidence,
        )

    selected_path = evidence.get("selectedMetadataRelativePath")
    used_path = evidence.get("usedMetadataRelativePath", selected_path)
    export_root = evidence.get("terraExportRootRelative")
    computed_origin_ok = _origins_equal(parsed_used, selected_origin) and _metadata_belongs_to_selected_frame(
        used_path=used_path,
        selected_path=selected_path,
        export_root=export_root,
    )
    explicit_origin_ok = evidence.get("srsOriginProvenanceOk")
    if explicit_origin_ok is False or (explicit_origin_ok is not True and not computed_origin_ok):
        return _base_result(
            provenance="AUTO_FAIL",
            reason=REASON_ORIGIN_MISMATCH,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )

    status = evidence.get("referenceEllipsoidProvenanceStatus")
    ellipsoid = evidence.get("referenceEllipsoid")
    if status == "CONFLICTING_EVIDENCE":
        return _base_result(
            provenance="HUMAN_REVIEW_REQUIRED",
            reason=REASON_ELLIPSOID_CONFLICT,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )
    if status == "PROVEN_NON_WGS84" or (status in APPROVED_ELLIPSOID_STATUSES and ellipsoid != "WGS84"):
        return _base_result(
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_NON_WGS84_UNSUPPORTED,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )
    if status not in APPROVED_ELLIPSOID_STATUSES or ellipsoid != "WGS84":
        return _base_result(
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_ELLIPSOID_NOT_PROVEN,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )

    mrk_valid = evidence.get("mrkEllhValid")
    semantic = evidence.get("heightObservationSemantic") or evidence.get("heightDatum")
    if semantic in CONTRADICTED_HEIGHT_SEMANTICS:
        return _base_result(
            provenance="AUTO_FAIL",
            reason=REASON_MRK_SEMANTIC_CONTRADICTION,
            allowed=False,
            mixed=True,
            origin=parsed_used,
            evidence=evidence,
        )
    if mrk_valid is not True or semantic not in APPROVED_ELLIPSOIDAL_SEMANTICS:
        return _base_result(
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_MRK_ELLH_NOT_PROVEN,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )

    terra_mode = evidence.get("terraVerticalMode")
    if terra_mode in {None, "", "UNKNOWN"}:
        return _base_result(
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_TERRA_VERTICAL_NOT_PROVEN,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )
    if str(terra_mode).strip().upper() != "DEFAULT":
        return _base_result(
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_TERRA_VERTICAL_UNSUPPORTED,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )

    if evidence.get("verticalOverrideFieldState") == FIELD_CONFLICT:
        return _base_result(
            provenance="HUMAN_REVIEW_REQUIRED",
            reason=REASON_OVERRIDE_CONFLICT,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )

    geoid = evidence.get("geoidConversionConfigured")
    if geoid == "YES":
        return _base_result(
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_GEOID_UNSUPPORTED,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )
    if geoid != "NO":
        return _base_result(
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_GEOID_NOT_PROVEN,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )

    override = evidence.get("verticalOverrideConfigured")
    if override == "YES":
        return _base_result(
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_OVERRIDE_UNSUPPORTED,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )
    if override != "NO":
        return _base_result(
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_OVERRIDE_NOT_PROVEN,
            allowed=False,
            mixed=False,
            origin=parsed_used,
            evidence=evidence,
        )

    return _base_result(
        provenance="AUTO_PASS",
        reason=REASON_HEIGHT_APPROVED,
        allowed=True,
        mixed=False,
        origin=parsed_used,
        evidence=evidence,
        extra={
            "referenceEllipsoid": "WGS84",
            "terraVerticalMode": "DEFAULT",
            "geoidConversionConfigured": "NO",
            "verticalOverrideConfigured": "NO",
            "sameVerticalFrame": True,
        },
    )


def evaluate_generic_height_from_sources(incoming_wall: Path, sources) -> dict:
    """Read selected metadata origin (allowed) and evaluate already-derived evidence."""
    from .frames import read_srs_origin

    evidence = dict(getattr(sources, "height_provenance_evidence", None) or {})
    meta_rel = getattr(sources, "metadata_xml_relative_path", None)
    origin_info = read_srs_origin(incoming_wall / meta_rel, relative_path=meta_rel)
    evidence.setdefault("selectedSrsOrigin", list(getattr(sources, "srs_origin")))
    evidence.setdefault("selectedMetadataRelativePath", meta_rel)
    evidence["usedSrsOrigin"] = origin_info["origin"]
    evidence["usedMetadataRelativePath"] = meta_rel
    return evaluate_generic_height_provenance(evidence)


def verify_height_datum(
    incoming_wall: Path,
    origin: list[float],
    *,
    sfm_geo_desc: str | None = None,
    legacy_mrk: str | None = None,
    require_legacy_proof: bool = True,
    height_evidence: dict | None = None,
) -> dict:
    if not require_legacy_proof:
        if height_evidence is None:
            return evaluate_generic_height_provenance(None)
        evidence = dict(height_evidence)
        evidence.setdefault("usedSrsOrigin", origin)
        evidence.setdefault("srsOrigin", origin)
        return evaluate_generic_height_provenance(evidence)
    sfm_rel = sfm_geo_desc or SFM_GEO_DESC
    legacy_rel = legacy_mrk or LEGACY_MRK
    sfm_path = incoming_wall / sfm_rel
    sfm = json.loads(sfm_path.read_text(encoding="utf-8"))
    gps = sfm["ref_GPS"]
    easting, northing = geographic_to_utm(gps["latitude"], gps["longitude"], 50)
    d_e = abs(easting - origin[0])
    d_n = abs(northing - origin[1])
    d_h = abs(float(gps["altitude"]) - origin[2])

    legacy = parse_mrk((incoming_wall / legacy_rel).read_text(encoding="utf-8", errors="replace"))
    match = None
    for rec in legacy.get("records") or []:
        try:
            if (
                abs(float(rec["latitude"]) - float(gps["latitude"])) < 1e-7
                and abs(float(rec["longitude"]) - float(gps["longitude"])) < 1e-7
                and abs(float(rec["ellipsoidalHeight"]) - float(gps["altitude"])) < 1e-3
            ):
                match = {
                    "photoId": rec.get("photoId"),
                    "ellipsoidalHeight": rec.get("ellipsoidalHeight"),
                    "heightDatum": rec.get("heightDatum"),
                    "sourceFile": legacy_rel,
                }
                break
        except (TypeError, ValueError):
            continue

    mixed = False
    problems = []
    if d_e > 0.05 or d_n > 0.05 or d_h > 0.05:
        mixed = True
        problems.append(
            f"SRSOrigin vs sfm_geo_desc.ref_GPS mismatch ΔE={d_e:.4f} ΔN={d_n:.4f} ΔH={d_h:.4f}"
        )
    if match is None:
        mixed = True
        problems.append("Could not re-prove sfm_geo_desc.ref_GPS equals a legacy MRK Ellh record")
    elif match.get("heightDatum") != "ellipsoidal":
        mixed = True
        problems.append("Matched MRK record is not labeled ellipsoidal")

    return {
        "heightDatumUsed": "ellipsoidal",
        "srsOrigin": origin,
        "sfmGeoDescRefGps": gps,
        "sfmFieldName": "altitude",
        "sfmFieldInterpretation": (
            "JSON key is 'altitude'; numerically identical to the matching MRK Ellh "
            "and to metadata.xml SRSOrigin Z. Treated as ellipsoidal height, not orthometric."
        ),
        "utmOfSfmRefGps": [easting, northing, float(gps["altitude"])],
        "deltaMetersENH": [d_e, d_n, d_h],
        "legacyMrkMatch": match,
        "horizontalCrs": UTM_EPSG,
        "mixedDatumDetected": mixed,
        "problems": problems,
        "noGeoidOffsetApplied": True,
    }


def projected_from_mrk_record(rec: dict) -> list[float]:
    metric = geodetic_to_projected_metric(rec["latitude"], rec["longitude"], rec["ellipsoidalHeight"])
    return metric.tolist()
