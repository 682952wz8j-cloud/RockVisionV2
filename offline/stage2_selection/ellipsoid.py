"""Rule C v1 — spec-governed GNSS reference-ellipsoid provenance.

Does not change projection math, Sim(3), or Terra selection.
Does not convert WGS84 ↔ CGCS2000.
Does not infer RTK source from RtkDiffAge, RtkFlag, or MRK Q.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .states import (
    APPROVED_CAPTURE_FAMILY_MATRICE_4,
    RULE_C_POLICY,
    SPEC_PROVENANCE_RECORD,
    ReasonCode,
    SelectionStatus,
)

FIELD_NOT_PRESENT = "FIELD_NOT_PRESENT"
FIELD_PRESENT_EMPTY = "FIELD_PRESENT_EMPTY"
FIELD_PRESENT_POPULATED = "FIELD_PRESENT_POPULATED"

# Closed Rule C v1 field tables. Not extensible search lists.
# Only these names are read for family / Network RTK / explicit reference-system evidence.
APPROVED_CAPTURE_FAMILY_FIELDS = (
    "drone-dji:ProductName",
    "drone-dji:DroneModel",
    "EXIF:Model",
)
APPROVED_NETWORK_RTK_OVERRIDE_FIELDS = (
    "NTRIPHost",
    "NTRIPPort",
    "NTRIPMountPoint",
)
APPROVED_EXPLICIT_REFERENCE_SYSTEM_FIELDS = (
    "RtkCoordinateSystem",
    "RtkDatum",
)

EVIDENCE_AUTHORITATIVE_ELLIPSOID = "AUTHORITATIVE_REFERENCE_ELLIPSOID_EVIDENCE"
EVIDENCE_AUTHORITATIVE_SOURCE = "AUTHORITATIVE_CAPTURE_SOURCE_EVIDENCE"
EVIDENCE_SUPPORTING = "SUPPORTING_SOURCE_EVIDENCE"
EVIDENCE_CONTRACT = "POSITIVE_CONTRACT_APPLICABILITY"
EVIDENCE_NOT_AUTHORITATIVE = "NOT_AUTHORITATIVE_REFERENCE_ELLIPSOID_EVIDENCE"

_M4_MODEL_RE = re.compile(r"^(M4E|M4T|M4D|M4TD|M4ET)$", re.I)
_M4_PRODUCT_RE = re.compile(r"\bMATRICE\s*4([ETD]|TD)?\b", re.I)
_WGS_RE = re.compile(r"^WGS[\s_-]?84$", re.I)
_CGCS_RE = re.compile(r"^CGCS[\s_-]?2000$", re.I)
_NAMED_GEOID_RE = re.compile(
    r"EGM96|EGM2008|NAVD88|GEOID|ORTHOMETRIC|KNgeoid|JGD2011",
    re.I,
)
_XMP_ATTR_RE = re.compile(r"(?:drone-dji|tiff|exif):([A-Za-z0-9_]+)=\"([^\"]*)\"")


def extract_jpeg_xmp_text(path: Path) -> str | None:
    data = path.read_bytes()
    start = data.find(b"<x:xmpmeta")
    if start < 0:
        return None
    end = data.find(b"</x:xmpmeta>", start)
    blob = data[start : end + 12] if end >= 0 else data[start : start + 16000]
    return blob.decode("utf-8", errors="replace")


def parse_xmp_attrs(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    return {key: value for key, value in _XMP_ATTR_RE.findall(text)}


def classify_field_presence(attrs: dict[str, str], name: str) -> tuple[str, str | None]:
    if name not in attrs:
        return FIELD_NOT_PRESENT, None
    raw = attrs[name]
    if str(raw).strip() == "":
        return FIELD_PRESENT_EMPTY, raw
    return FIELD_PRESENT_POPULATED, raw


def _normalize_ellipsoid_name(raw: str) -> str | None:
    text = str(raw).strip()
    if not text:
        return None
    if _WGS_RE.match(text):
        return "WGS84"
    if _CGCS_RE.match(text):
        return "CGCS2000"
    return "OTHER_NAMED"


def identify_capture_family(
    *,
    product_name: str | None = None,
    drone_model: str | None = None,
    exif_model: str | None = None,
) -> str:
    """Normalize approved camera-family fields only. Wall ID / folder / path are ignored."""
    values = {
        "drone-dji:ProductName": product_name,
        "drone-dji:DroneModel": drone_model,
        "EXIF:Model": exif_model,
    }
    for field in APPROVED_CAPTURE_FAMILY_FIELDS:
        token = values.get(field)
        if not token or str(token).strip() in {"", "missing"}:
            continue
        text = str(token).strip()
        if _M4_MODEL_RE.match(text) or _M4_PRODUCT_RE.search(text):
            return APPROVED_CAPTURE_FAMILY_MATRICE_4
    return "UNKNOWN"


def _evidence(
    *,
    path: str | None,
    field: str,
    raw_value,
    evidence_class: str,
    note: str | None = None,
) -> dict:
    row = {
        "path": path,
        "field": field,
        "rawValue": raw_value,
        "evidenceClass": evidence_class,
    }
    if note:
        row["note"] = note
    return row


def _ellh_valid(records: list[dict] | None) -> tuple[bool, int]:
    count = 0
    for rec in records or []:
        value = rec.get("ellipsoidalHeight")
        try:
            float(value)
            count += 1
        except (TypeError, ValueError):
            continue
    return count > 0, count


def collect_terra_vertical_evidence(incoming: Path, export_root_rel: str | None) -> dict:
    if not export_root_rel:
        return {
            "terraVerticalMode": "UNKNOWN",
            "geoidConversionConfigured": "UNKNOWN",
            "evidence": [],
        }
    root = incoming / export_root_rel
    evidence: list[dict] = []
    vertical_mode = "UNKNOWN"
    geoid = "UNKNOWN"

    report = root / "report" / "model_report.json"
    if report.is_file():
        rel = report.relative_to(incoming).as_posix()
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            raw_vertical = payload.get("output vertical coordinate")
            raw_output = payload.get("output coordinate")
            if raw_output is not None:
                evidence.append(
                    _evidence(
                        path=rel,
                        field="output coordinate",
                        raw_value=raw_output,
                        evidence_class=EVIDENCE_NOT_AUTHORITATIVE,
                        note="Terra output CRS is not capture reference ellipsoid.",
                    )
                )
            if isinstance(raw_vertical, str):
                if raw_vertical.strip().lower() == "default":
                    vertical_mode = "DEFAULT"
                    geoid = "NO"
                elif _NAMED_GEOID_RE.search(raw_vertical):
                    vertical_mode = "OTHER"
                    geoid = "YES"
                else:
                    vertical_mode = "OTHER"
                    geoid = "YES"
                evidence.append(
                    _evidence(
                        path=rel,
                        field="output vertical coordinate",
                        raw_value=raw_vertical,
                        evidence_class=EVIDENCE_CONTRACT,
                    )
                )

    sdk = root / "SDK_Log.txt"
    if sdk.is_file():
        rel = sdk.relative_to(incoming).as_posix()
        override = None
        for line in sdk.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("<TerraLog>"):
                continue
            match = re.search(r'"override_vertical_cs"\s*:\s*"([^"]*)"', line)
            if match:
                override = match.group(1)
                break
        if override is not None:
            presence = FIELD_PRESENT_EMPTY if override.strip() == "" else FIELD_PRESENT_POPULATED
            evidence.append(
                _evidence(
                    path=rel,
                    field="override_vertical_cs",
                    raw_value=override,
                    evidence_class=EVIDENCE_CONTRACT,
                    note=presence,
                )
            )
            if override.strip():
                geoid = "YES"

    return {
        "terraVerticalMode": vertical_mode,
        "geoidConversionConfigured": geoid,
        "evidence": evidence,
    }


def _exif_model(path: Path) -> str | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(path) as image:
        value = image.getexif().get(0x0110)
    if value is None:
        return None
    text = value.decode("ascii", errors="replace") if isinstance(value, bytes) else str(value)
    return text.strip("\x00").strip() or None


def _exif_gps_map_datum(path: Path) -> str | None:
    try:
        from PIL import ExifTags, Image
    except ImportError:
        return None
    with Image.open(path) as image:
        exif = image.getexif()
        gps = exif.get_ifd(0x8825) if hasattr(exif, "get_ifd") else {}
    for key, value in (gps or {}).items():
        if ExifTags.GPSTAGS.get(key) == "GPSMapDatum":
            text = value.decode("ascii", errors="replace") if isinstance(value, bytes) else str(value)
            return text.strip("\x00").strip() or None
    return None


def _inspect_capture_images(
    incoming: Path,
    capture_relative_paths: list[str],
    camera_models: list[str] | None,
) -> dict:
    family_hits: list[dict] = []
    ntrip_fields: dict[str, dict] = {
        name: {"presence": FIELD_NOT_PRESENT, "values": [], "paths": []}
        for name in APPROVED_NETWORK_RTK_OVERRIDE_FIELDS
    }
    explicit: list[dict] = []
    gps_map_datum: list[dict] = []
    xmp_evidence: list[dict] = []
    models_seen: list[str] = []

    for index, rel in enumerate(capture_relative_paths):
        path = incoming / rel
        model = None
        if camera_models and index < len(camera_models):
            model = camera_models[index]
            if model and model not in models_seen:
                models_seen.append(model)
        attrs: dict[str, str] = {}
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}:
            attrs = parse_xmp_attrs(extract_jpeg_xmp_text(path))
        if model is None and path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}:
            model = _exif_model(path)
        if model and model not in models_seen:
            models_seen.append(model)
        product = attrs.get("ProductName")
        drone = attrs.get("DroneModel")
        if identify_capture_family(product_name=product, drone_model=drone, exif_model=model) == APPROVED_CAPTURE_FAMILY_MATRICE_4:
            family_hits.append(
                {
                    "relativePath": rel,
                    "cameraModel": model,
                    "ProductName": product,
                    "DroneModel": drone,
                }
            )
        for name in APPROVED_NETWORK_RTK_OVERRIDE_FIELDS:
            presence, raw = classify_field_presence(attrs, name)
            if presence == FIELD_NOT_PRESENT:
                continue
            ntrip_fields[name]["presence"] = presence
            ntrip_fields[name]["values"].append(raw)
            ntrip_fields[name]["paths"].append(rel)
            if presence == FIELD_PRESENT_POPULATED:
                xmp_evidence.append(
                    _evidence(
                        path=rel,
                        field=name,
                        raw_value=raw,
                        evidence_class=EVIDENCE_AUTHORITATIVE_SOURCE,
                    )
                )
        for name in APPROVED_EXPLICIT_REFERENCE_SYSTEM_FIELDS:
            presence, raw = classify_field_presence(attrs, name)
            if presence != FIELD_PRESENT_POPULATED:
                continue
            named = _normalize_ellipsoid_name(raw)
            explicit.append(
                _evidence(
                    path=rel,
                    field=name,
                    raw_value=raw,
                    evidence_class=EVIDENCE_AUTHORITATIVE_ELLIPSOID,
                    note=named,
                )
            )
        datum = _exif_gps_map_datum(path) if path.is_file() else None
        if datum and not any(item.get("rawValue") == datum for item in gps_map_datum):
            gps_map_datum.append(
                _evidence(
                    path=rel,
                    field="EXIF:GPSMapDatum",
                    raw_value=datum,
                    evidence_class=EVIDENCE_SUPPORTING,
                    note="Conventional EXIF GPS label. Not PROVEN_WGS84.",
                )
            )

    unique_family = None
    if family_hits:
        unique_family = APPROVED_CAPTURE_FAMILY_MATRICE_4

    populated_ntrip = [
        name
        for name, item in ntrip_fields.items()
        if item["presence"] == FIELD_PRESENT_POPULATED
    ]
    return {
        "captureFamily": unique_family,
        "familyHits": family_hits,
        "cameraModelsSeen": models_seen,
        "ntripFields": ntrip_fields,
        "networkRtkDetected": bool(populated_ntrip),
        "populatedNtripFields": populated_ntrip,
        "explicitDatumEvidence": explicit,
        "alternateReferenceEvidence": [
            item for item in explicit if item.get("note") in {"CGCS2000", "OTHER_NAMED"}
        ],
        "gpsMapDatumEvidence": gps_map_datum,
        "xmpEvidence": xmp_evidence,
    }


def _explicit_named_systems(explicit: list[dict]) -> list[str]:
    names: list[str] = []
    for item in explicit:
        named = item.get("note")
        if named in {"WGS84", "CGCS2000", "OTHER_NAMED"} and named not in names:
            names.append(named)
    return names


def evaluate_rule_c(
    incoming: Path,
    *,
    capture_relative_paths: list[str] | None = None,
    camera_models: list[str] | None = None,
    mrk_relative_path: str | None = None,
    mrk_records: list[dict] | None = None,
    terra_export_root_relative: str | None = None,
    gps_map_datum_values: list[dict] | None = None,
) -> dict:
    paths = list(capture_relative_paths or [])
    inspected = _inspect_capture_images(incoming, paths, camera_models)
    if gps_map_datum_values:
        seen = {item.get("rawValue") for item in inspected["gpsMapDatumEvidence"]}
        for item in gps_map_datum_values:
            if item.get("rawValue") not in seen:
                inspected["gpsMapDatumEvidence"].append(item)
                seen.add(item.get("rawValue"))

    ellh_ok, ellh_count = _ellh_valid(mrk_records)
    terra = collect_terra_vertical_evidence(incoming, terra_export_root_relative)
    explicit = inspected["explicitDatumEvidence"]
    named = _explicit_named_systems(explicit)
    alternate = list(inspected["alternateReferenceEvidence"])
    network = inspected["networkRtkDetected"]

    rtk_source = "UNKNOWN"
    rtk_source_evidence: list[dict] = []
    for name, item in inspected["ntripFields"].items():
        rtk_source_evidence.append(
            _evidence(
                path=item["paths"][0] if item["paths"] else None,
                field=name,
                raw_value=item["values"][0] if item["values"] else None,
                evidence_class=EVIDENCE_AUTHORITATIVE_SOURCE
                if item["presence"] == FIELD_PRESENT_POPULATED
                else EVIDENCE_SUPPORTING,
                note=item["presence"],
            )
        )
    if network:
        rtk_source = "NETWORK_RTK"

    family = inspected["captureFamily"]
    family_evidence = []
    if inspected["familyHits"]:
        hit = inspected["familyHits"][0]
        if hit.get("ProductName"):
            family_evidence.append(
                _evidence(
                    path=hit["relativePath"],
                    field="drone-dji:ProductName",
                    raw_value=hit["ProductName"],
                    evidence_class=EVIDENCE_CONTRACT,
                )
            )
        if hit.get("DroneModel"):
            family_evidence.append(
                _evidence(
                    path=hit["relativePath"],
                    field="drone-dji:DroneModel",
                    raw_value=hit["DroneModel"],
                    evidence_class=EVIDENCE_CONTRACT,
                )
            )
        if hit.get("cameraModel"):
            family_evidence.append(
                _evidence(
                    path=hit["relativePath"],
                    field="EXIF:Model",
                    raw_value=hit["cameraModel"],
                    evidence_class=EVIDENCE_CONTRACT,
                )
            )
    elif camera_models:
        family_evidence.append(
            _evidence(
                path=paths[0] if paths else None,
                field="EXIF:Model",
                raw_value=camera_models[0],
                evidence_class=EVIDENCE_SUPPORTING,
                note="Not an approved Matrice 4 Series identifier.",
            )
        )

    gps_map = inspected["gpsMapDatumEvidence"]
    for item in gps_map:
        item.setdefault("evidenceClass", EVIDENCE_SUPPORTING)

    height_semantic = "GNSS_GEODETIC_ELLIPSOIDAL_HEIGHT" if ellh_ok else "UNKNOWN"
    ellipsoid_evidence: list[dict] = []
    if ellh_ok:
        ellipsoid_evidence.append(
            _evidence(
                path=mrk_relative_path,
                field="Ellh",
                raw_value=f"validEllhRecords={ellh_count}",
                evidence_class=EVIDENCE_CONTRACT,
                note="Height semantic only. Not ellipsoid identity.",
            )
        )
    ellipsoid_evidence.extend(explicit)
    ellipsoid_evidence.extend(gps_map)

    conflict = len(named) > 1
    proven_wgs = named == ["WGS84"]
    proven_non = bool(named) and "WGS84" not in named

    spec_default_ok = (
        family == APPROVED_CAPTURE_FAMILY_MATRICE_4
        and ellh_ok
        and terra["terraVerticalMode"] == "DEFAULT"
        and terra["geoidConversionConfigured"] == "NO"
        and not network
        and not alternate
        and not named
        and not conflict
    )

    if conflict:
        status = "CONFLICTING_EVIDENCE"
        ellipsoid = "UNKNOWN"
        spec_default = False
        datum_compat = "UNKNOWN"
        terminal = SelectionStatus.HUMAN_REVIEW_REQUIRED
        reason = ReasonCode.RULE_C_CONFLICTING_EVIDENCE
    elif proven_wgs:
        status = "PROVEN_WGS84"
        ellipsoid = "WGS84"
        spec_default = False
        datum_compat = "COMPATIBLE_WITH_APPROVED_STAGE2_CRS"
        terminal = SelectionStatus.AUTO_PASS
        reason = ReasonCode.RULE_C_PROVEN_WGS84
        if network:
            rtk_source = "NETWORK_RTK"
    elif proven_non:
        status = "PROVEN_NON_WGS84"
        ellipsoid = named[0]
        spec_default = False
        datum_compat = "INSUFFICIENT_STAGE2_CRS_CAPABILITY"
        terminal = SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED
        reason = ReasonCode.RULE_C_INSUFFICIENT_STAGE2_CRS_CAPABILITY
    elif network:
        status = "UNKNOWN"
        ellipsoid = "UNKNOWN"
        spec_default = False
        datum_compat = "UNKNOWN"
        terminal = SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED
        reason = ReasonCode.RULE_C_NETWORK_RTK_ELLIPSOID_UNKNOWN
    elif spec_default_ok:
        status = "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC"
        ellipsoid = "WGS84"
        spec_default = True
        datum_compat = "COMPATIBLE_WITH_APPROVED_STAGE2_CRS"
        terminal = SelectionStatus.AUTO_PASS
        reason = ReasonCode.RULE_C_DEFAULT_WGS84_BY_APPROVED_DJI_SPEC
    else:
        status = "UNKNOWN"
        ellipsoid = "UNKNOWN"
        spec_default = False
        datum_compat = "UNKNOWN"
        terminal = SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED
        reason = ReasonCode.RULE_C_UNKNOWN

    default_guards = {
        "approvedCaptureFamily": family == APPROVED_CAPTURE_FAMILY_MATRICE_4,
        "mrkEllhValid": ellh_ok,
        "terraVerticalDefault": terra["terraVerticalMode"] == "DEFAULT",
        "geoidConversionConfiguredNo": terra["geoidConversionConfigured"] == "NO",
        "noNetworkRtk": not network,
        "noApprovedNetworkRtkOverride": not network,
        "noApprovedExplicitNonWgs84": "CGCS2000" not in named and "OTHER_NAMED" not in named,
        "noExplicitNonWgs84": "CGCS2000" not in named and "OTHER_NAMED" not in named,
        "noConflictingReferenceEvidence": not conflict,
        "gpsMapDatumNotUsedAsProof": True,
        "epsg32650NotUsedAsProof": True,
        "rtkDiffAgeNotUsedAsSource": True,
        "mrkQNotUsedAsSource": True,
        "numericalSanityNotUsedAsProof": True,
    }

    return {
        "policy": RULE_C_POLICY,
        "specProvenanceRecord": SPEC_PROVENANCE_RECORD,
        "captureFamily": family or "UNKNOWN",
        "captureFamilyEvidence": family_evidence,
        "rtkSource": rtk_source,
        "rtkSourceEvidence": rtk_source_evidence,
        "networkRtk": {
            "detected": network,
            "fieldsInspected": {
                name: {
                    "presence": item["presence"],
                    "rawValue": item["values"][0] if item["values"] else None,
                    "path": item["paths"][0] if item["paths"] else None,
                }
                for name, item in inspected["ntripFields"].items()
            },
            "populatedFields": inspected["populatedNtripFields"],
            "note": "Network RTK does not imply CGCS2000. It blocks the WGS84 default unless independently proven.",
        },
        "heightObservationSemantic": height_semantic,
        "mrkEllh": {
            "path": mrk_relative_path,
            "valid": ellh_ok,
            "validRecordCount": ellh_count,
        },
        "referenceEllipsoid": ellipsoid,
        "referenceEllipsoidEvidence": ellipsoid_evidence,
        "referenceEllipsoidProvenanceStatus": status,
        "terraVerticalMode": terra["terraVerticalMode"],
        "geoidConversionConfigured": terra["geoidConversionConfigured"],
        "terraVerticalEvidence": terra["evidence"],
        "alternateReferenceEvidence": alternate,
        "gpsMapDatumEvidence": gps_map,
        "datumCompatibilityStatus": datum_compat,
        "specDefaultInvoked": spec_default,
        "defaultBranchGuards": default_guards,
        "terminalStatus": terminal.value,
        "reasonCode": reason.value,
        "reasonCodes": (
            [reason.value, ReasonCode.RULE_C_PROVEN_NON_WGS84.value]
            if proven_non
            else [reason.value]
        ),
        "outputCrsMustNotBeCopiedToCapture": True,
        "closedFieldTables": {
            "APPROVED_CAPTURE_FAMILY_FIELDS": list(APPROVED_CAPTURE_FAMILY_FIELDS),
            "APPROVED_NETWORK_RTK_OVERRIDE_FIELDS": list(APPROVED_NETWORK_RTK_OVERRIDE_FIELDS),
            "APPROVED_EXPLICIT_REFERENCE_SYSTEM_FIELDS": list(APPROVED_EXPLICIT_REFERENCE_SYSTEM_FIELDS),
        },
        "recursiveStringSearchAuthorized": False,
    }


def evaluate_rule_c_from_selection(
    incoming: Path,
    *,
    selected_capture: dict | None,
    selected_mrk: dict | None,
    mrk_candidates: list[dict],
    terra_result: dict,
    discovered_images: list[dict],
) -> dict:
    paths = list((selected_capture or {}).get("memberRelativePaths") or [])
    models_by_path = {
        img.get("relativePath"): img.get("cameraModel")
        for img in discovered_images
        if img.get("relativePath")
    }
    camera_models = [models_by_path.get(rel) for rel in paths]
    mrk_path = (selected_mrk or {}).get("relativePath")
    records = None
    for cand in mrk_candidates:
        if cand.get("relativePath") == mrk_path:
            records = cand.get("records")
            break
    gps_map: list[dict] = []
    for rel in paths:
        img = next((item for item in discovered_images if item.get("relativePath") == rel), None)
        datum = (img or {}).get("gpsMapDatum")
        if datum and datum not in {"missing", None, ""}:
            gps_map.append(
                _evidence(
                    path=rel,
                    field="EXIF:GPSMapDatum",
                    raw_value=datum,
                    evidence_class=EVIDENCE_SUPPORTING,
                    note="Conventional EXIF GPS label. Not PROVEN_WGS84.",
                )
            )
    export_root = (terra_result.get("terraExportRoot") or {}).get("relativePath")
    return evaluate_rule_c(
        incoming,
        capture_relative_paths=paths,
        camera_models=camera_models,
        mrk_relative_path=mrk_path,
        mrk_records=records,
        terra_export_root_relative=export_root,
        gps_map_datum_values=gps_map,
    )


def evaluate_rule_c_session(
    incoming: Path,
    *,
    session_id: str,
    capture_relative_paths: list[str] | None = None,
    camera_models: list[str] | None = None,
    mrk_relative_path: str | None = None,
    mrk_records: list[dict] | None = None,
    terra_export_root_relative: str | None = None,
) -> dict:
    """Evaluate one capture session. Family is never inherited from another session."""
    result = evaluate_rule_c(
        incoming,
        capture_relative_paths=capture_relative_paths,
        camera_models=camera_models,
        mrk_relative_path=mrk_relative_path,
        mrk_records=mrk_records,
        terra_export_root_relative=terra_export_root_relative,
    )
    result["sessionId"] = session_id
    result["crossSessionFamilyInheritance"] = False
    return result
