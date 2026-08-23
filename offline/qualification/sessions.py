"""Capture-session identity. Do not collapse legacy and 2026-08-23 pools."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .associate import dji_stamp_from_filename, parse_exif_time
from .status import ProvenanceStatus, claim

MISSING = "missing"

LEGACY_DJI = "legacy_dji_20260811"
LEGACY_TERRA = "legacy_terra_rtk_20260812"
DJI_20260823 = "dji_20260823"
IPHONE_20260823 = "iphone_20260823"
UNKNOWN = "unknown"
NOT_CAPTURE = "not_a_capture"

IPHONE_NAME = re.compile(r"^IMG_\d{4}\.(HEIC|HEIF|JPE?G)$", re.I)
DJI_NAME = re.compile(r"^DJI_\d{14}_\d{4}_[A-Z]\.(JPE?G)$", re.I)


def _date_from_exif(value: str) -> str | None:
    parsed = parse_exif_time(value)
    return parsed.date().isoformat() if parsed else None


def assign_capture_session(image: dict) -> dict:
    rel = image.get("relativePath") or ""
    name = image.get("filename") or ""
    role = image.get("role")
    make = str(image.get("cameraMake") or "")
    model = str(image.get("cameraModel") or "")
    ext = Path(name).suffix.lower()
    stamp = dji_stamp_from_filename(name)
    exif_date = _date_from_exif(str(image.get("captureTimestamp") or ""))

    session = UNKNOWN
    device = MISSING
    capture_date = exif_date or MISSING
    evidence: list[str] = []

    if role not in {"originalCameraImage"}:
        session = NOT_CAPTURE
        device = "notACameraExposure"
        capture_date = MISSING
        evidence.append(f"Role {role} is not a camera capture session.")
    elif "DJI_202608231218_006" in rel.replace("\\", "/") or (
        stamp and stamp.strftime("%Y%m%d") == "20260823" and DJI_NAME.match(name)
    ):
        session = DJI_20260823
        device = "DJI"
        capture_date = stamp.date().isoformat() if stamp else (exif_date or "2026-08-23")
        evidence.append("2026-08-23 DJI filename / capture folder.")
    elif stamp and stamp.strftime("%Y%m%d") == "20260811":
        session = LEGACY_DJI
        device = "DJI"
        capture_date = "2026-08-11"
        evidence.append("Legacy DJI filename date 2026-08-11.")
    elif ext in {".heic", ".heif"} or IPHONE_NAME.match(name) or "iphone" in rel.lower() or "0823" in rel:
        apple = "apple" in make.lower() or "iphone" in model.lower()
        device = model if model not in {MISSING, ""} else ("iPhone" if apple or IPHONE_NAME.match(name) else MISSING)
        if exif_date == "2026-08-23" or "0823" in rel or "iphone拍摄" in rel:
            session = IPHONE_20260823
            capture_date = exif_date or "2026-08-23"
            evidence.append("2026-08-23 iPhone HEIC/JPEG capture.")
        else:
            session = "iphone_other"
            capture_date = exif_date or MISSING
            evidence.append("iPhone/HEIC original, date not 2026-08-23.")
    elif stamp:
        session = f"dji_{stamp.strftime('%Y%m%d')}"
        device = "DJI"
        capture_date = stamp.date().isoformat()
        evidence.append("DJI filename date is neither 2026-08-11 nor 2026-08-23.")
    else:
        evidence.append("No DJI filename stamp or iPhone HEIC identity.")

    image["captureSession"] = session
    image["sourceDevice"] = device
    image["captureDate"] = capture_date
    image["qualificationStatus"] = (image.get("classification") or {}).get("status") or MISSING
    image["sessionAssignment"] = claim(ProvenanceStatus.PROVEN if session not in {UNKNOWN, "iphone_other"} else ProvenanceStatus.UNKNOWN, f"{name} → {session}", evidence)
    return image


def session_summaries(images: list[dict], associations: list[dict], rtk_reports: list[dict]) -> dict:
    by_session: dict[str, list[dict]] = {}
    for image in images:
        by_session.setdefault(image.get("captureSession") or UNKNOWN, []).append(image)

    assoc_by_image = {item["image"]: item for item in associations}
    rtk_by_session = _rtk_sessions(rtk_reports)

    out = {}
    for session_id, rows in by_session.items():
        originals = [row for row in rows if row.get("role") == "originalCameraImage"]
        session_assoc = [assoc_by_image[row["relativePath"]] for row in originals if row["relativePath"] in assoc_by_image]
        matched = [item for item in session_assoc if item.get("matchedMrk")]
        unmatched_images = [item for item in session_assoc if not item.get("matchedMrk")]
        mrk_ids = _mrk_photo_ids(rtk_reports, session_id)
        matched_ids = {
            (item.get("mrkNearest") or {}).get("photoId")
            for item in matched
            if isinstance((item.get("mrkNearest") or {}).get("photoId"), int)
        }
        unmatched_mrk = [photo_id for photo_id in mrk_ids if photo_id not in matched_ids]
        methods = sorted({item.get("associationMethod") or "none" for item in session_assoc})
        statuses = {item["association"]["status"] for item in session_assoc}
        if session_id == LEGACY_DJI and any(item["association"]["status"] == ProvenanceStatus.CONTRADICTED.value for item in session_assoc):
            pairing = ProvenanceStatus.CONTRADICTED.value
        elif session_id == DJI_20260823 and session_assoc and all(
            item["association"]["status"] == ProvenanceStatus.PROVEN.value for item in session_assoc
        ):
            pairing = ProvenanceStatus.PROVEN.value
        elif ProvenanceStatus.PROVEN.value in statuses:
            pairing = ProvenanceStatus.PROVEN.value
        elif ProvenanceStatus.CONTRADICTED.value in statuses:
            pairing = ProvenanceStatus.CONTRADICTED.value
        elif ProvenanceStatus.SUPPORTED.value in statuses:
            pairing = ProvenanceStatus.SUPPORTED.value
        else:
            pairing = ProvenanceStatus.UNKNOWN.value
        out[session_id] = {
            "captureSession": session_id,
            "imageCount": len(rows),
            "originalCameraImages": len(originals),
            "colmapAutoCandidates": sum(1 for row in rows if row.get("colmapSourceCandidate")),
            "sourceDevices": sorted({str(row.get("sourceDevice")) for row in rows}),
            "captureDates": sorted({str(row.get("captureDate")) for row in rows}),
            "imageMrkStatus": pairing,
            "matchedImageCount": len(matched),
            "unmatchedImageCount": len(unmatched_images),
            "matchedMrkCount": len(matched_ids),
            "unmatchedMrkCount": len(unmatched_mrk),
            "associationMethods": methods,
            "rtkFiles": rtk_by_session.get(session_id, []),
        }
    out["_rtkOnly"] = {key: value for key, value in rtk_by_session.items() if key not in out}
    return out


def _rtk_sessions(rtk_reports: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for parsed in rtk_reports:
        rel = parsed.get("relativePath") or parsed.get("filename") or ""
        name = parsed.get("filename") or Path(rel).name
        stamp = dji_stamp_from_filename(name)
        if "DJI_202608231218_006" in rel.replace("\\", "/") or (stamp and stamp.strftime("%Y%m%d") == "20260823"):
            session = DJI_20260823
        elif stamp and stamp.strftime("%Y%m%d") == "20260812":
            session = LEGACY_TERRA
        else:
            session = UNKNOWN
        grouped.setdefault(session, []).append(rel)
    return grouped


def _mrk_photo_ids(rtk_reports: list[dict], session_id: str) -> list[int]:
    ids: list[int] = []
    grouped = _rtk_sessions(rtk_reports)
    wanted = set(grouped.get(session_id) or [])
    for parsed in rtk_reports:
        rel = parsed.get("relativePath") or parsed.get("filename") or ""
        if parsed.get("fileType") != "djiMrk" or rel not in wanted:
            continue
        for rec in parsed.get("records") or []:
            if isinstance(rec.get("photoId"), int):
                ids.append(rec["photoId"])
    return ids


def iphone_qualification(images: list[dict], duplicate_paths: set[str]) -> dict:
    rows = [img for img in images if img.get("captureSession") == IPHONE_20260823]
    unreadable = [
        img
        for img in rows
        if not isinstance((img.get("dimensions") or {}).get("width"), int)
        or not isinstance((img.get("dimensions") or {}).get("height"), int)
    ]
    hash_dups = [img for img in rows if img.get("relativePath") in duplicate_paths]
    return {
        "captureSession": IPHONE_20260823,
        "originalPhotos": len(rows),
        "usableCandidates": "UNKNOWN",
        "possibleDuplicates": len(hash_dups),
        "obviousUnusable": len(unreadable),
        "autoColmap": False,
        "notes": [
            "iPhone files are qualified as an independent capture session.",
            "They are not auto-selected as COLMAP input.",
            "Blur / visual overlap / coverage cannot be proven from metadata alone.",
        ],
    }


def colmap_readiness(sessions: dict, images: list[dict], incoming_unchanged: bool) -> dict:
    dji = [img for img in images if img.get("captureSession") == DJI_20260823 and img.get("role") == "originalCameraImage"]
    readable = [
        img
        for img in dji
        if isinstance((img.get("dimensions") or {}).get("width"), int)
        and isinstance((img.get("dimensions") or {}).get("height"), int)
    ]
    pairing = (sessions.get(DJI_20260823) or {}).get("imageMrkStatus")
    reasons = []
    ready = True
    if not incoming_unchanged:
        ready = False
        reasons.append("incoming hashes changed during qualification")
    if len(readable) < 10:
        ready = False
        reasons.append(f"only {len(readable)} readable 2026-08-23 DJI originals")
    if any(img.get("qualificationStatus") == ProvenanceStatus.CONTRADICTED.value for img in dji):
        ready = False
        reasons.append("2026-08-23 DJI originals are contradicted as camera exposures")
    if not dji:
        ready = False
        reasons.append("no 2026-08-23 DJI original camera session")
    overlap = "SUPPORTED" if len(readable) >= 10 else "UNKNOWN"
    reasons.append(
        "Multi-view overlap from metadata (time sequence + GPS) is SUPPORTED, not visually PROVEN."
    )
    if pairing != ProvenanceStatus.PROVEN.value:
        reasons.append(f"2026-08-23 image↔MRK is {pairing}; RTK same-batch is a strong expectation.")
    return {
        "status": "READY" if ready else "NOT READY",
        "newDjiOriginals": len(dji),
        "newDjiReadable": len(readable),
        "imageMrkStatus": pairing or ProvenanceStatus.UNKNOWN.value,
        "visualOverlap": overlap,
        "reasons": reasons,
        "colmapNotRun": True,
    }
