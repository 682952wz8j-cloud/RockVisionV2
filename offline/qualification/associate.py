from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path

from .status import ProvenanceStatus, claim

MISSING = "missing"

DJI_FILE = re.compile(r"^DJI_(\d{14})_(\d{4})_([A-Za-z])\.", re.I)


def parse_exif_time(value: str) -> datetime | None:
    if not value or value == MISSING:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def dji_stamp_from_filename(name: str) -> datetime | None:
    parts = dji_filename_parts(name)
    return parts["stamp"] if parts else None


def dji_filename_parts(name: str) -> dict | None:
    match = DJI_FILE.match(name)
    if not match:
        return None
    try:
        stamp = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return {
        "stamp": stamp,
        "sequence": int(match.group(2)),
        "channel": match.group(3).upper(),
        "date": match.group(1)[:8],
    }


def _parent_key(rel: str) -> str:
    return Path(rel).parent.as_posix()


def associate_images_to_mrk(images: list[dict], mrk_files: list[dict]) -> list[dict]:
    by_folder_id: dict[tuple[str, int], list[dict]] = {}
    mrk_dates: set[str] = set()
    mrk_records: list[dict] = []
    for parsed in mrk_files:
        if parsed.get("fileType") != "djiMrk":
            continue
        rel = parsed.get("relativePath") or parsed.get("filename") or ""
        name = parsed.get("filename") or Path(rel).name
        parts = dji_filename_parts(name)
        if parts:
            mrk_dates.add(parts["date"])
        parent = _parent_key(rel)
        for rec in parsed.get("records") or []:
            item = {
                **rec,
                "sourceFile": rel,
                "mrkParent": parent,
                "mrkDate": parts["date"] if parts else None,
            }
            photo_id = rec.get("photoId")
            if isinstance(photo_id, int):
                by_folder_id.setdefault((parent, photo_id), []).append(item)
            mrk_records.append(item)

    associations = []
    used_mrk: set[tuple[str, int]] = set()
    for image in images:
        if image["role"] != "originalCameraImage":
            continue
        name = image["filename"]
        parts = dji_filename_parts(name)
        parent = _parent_key(image["relativePath"])
        lat = image.get("gpsLatitude", MISSING)
        lon = image.get("gpsLongitude", MISSING)
        evidence: list[str] = []
        source = "none"
        altitude_datum = MISSING
        if lat != MISSING:
            source = "exifGps"
            altitude_datum = "exifUnspecified"
            evidence.append("Image EXIF contains GPS latitude/longitude.")
            evidence.append("EXIF altitude datum is not labeled ellipsoidal vs orthometric.")

        matched = None
        method = "none"
        if parts:
            evidence.append(f"DJI filename timestamp {parts['stamp'].isoformat(sep=' ')} sequence {parts['sequence']:04d}")
            candidates = by_folder_id.get((parent, parts["sequence"])) or []
            if len(candidates) == 1:
                matched = candidates[0]
                method = (
                    "filename_sequence==MRK.photoId + same_parent_directory"
                    if parent not in {".", ""}
                    else "filename_sequence==MRK.photoId at inventory root"
                )
                used_mrk.add((parent, parts["sequence"]))
            elif len(candidates) > 1:
                evidence.append(f"Ambiguous MRK photoId {parts['sequence']} in {parent}.")

        same_calendar = bool(parts and mrk_dates and parts["date"] in mrk_dates)
        if parts and mrk_dates and parts["date"] not in mrk_dates:
            evidence.append(
                f"Filename date {parts['date']} does not match MRK filename dates {sorted(mrk_dates)}."
            )
        elif same_calendar:
            evidence.append("Filename calendar date matches an MRK filename date (not sufficient alone).")

        if matched:
            evidence.append(
                f"Matched MRK {matched.get('sourceFile')} photoId={matched.get('photoId')} by {method}."
            )
            if matched.get("mrkDate") and parts and matched["mrkDate"] != parts["date"]:
                status = ProvenanceStatus.CONTRADICTED
                statement = "Same folder/sequence as an MRK record, but filename dates disagree"
            elif parent not in {".", ""}:
                status = ProvenanceStatus.PROVEN
                statement = "Same parent directory and filename sequence equals MRK photoId"
            elif parts and matched.get("mrkDate") == parts["date"]:
                status = ProvenanceStatus.SUPPORTED
                statement = "Sequence equals MRK photoId at inventory root; no distinctive session folder"
            else:
                status = ProvenanceStatus.UNKNOWN
                statement = "Sequence match at inventory root without a session folder"
        elif not mrk_records:
            status = ProvenanceStatus.PROVEN if lat != MISSING else ProvenanceStatus.UNKNOWN
            statement = "EXIF GPS only; no MRK records available" if lat != MISSING else "No GPS and no MRK match"
        elif parts and mrk_dates and parts["date"] not in mrk_dates and lat != MISSING:
            status = ProvenanceStatus.CONTRADICTED
            statement = "EXIF GPS exists, but this exposure is not the MRK/RINEX session"
        elif same_calendar:
            status = ProvenanceStatus.UNKNOWN
            statement = "Same calendar date as MRK is not a deterministic exposure match"
        else:
            status = ProvenanceStatus.UNKNOWN
            statement = "No deterministic image ↔ MRK identifier"

        best = None
        best_dist = None
        if lat != MISSING and lon != MISSING:
            pool = [matched] if matched else mrk_records
            for rec in pool:
                if rec.get("latitude") == MISSING:
                    continue
                try:
                    dist = math.hypot(float(lat) - float(rec["latitude"]), float(lon) - float(rec["longitude"]))
                except (TypeError, ValueError):
                    continue
                if best_dist is None or dist < best_dist:
                    best = rec
                    best_dist = dist
            if best_dist is not None:
                evidence.append(f"Nearest compared MRK record is {best_dist:.8f} degrees away.")

        associations.append(
            {
                "image": image["relativePath"],
                "captureSession": image.get("captureSession", MISSING),
                "latitude": lat,
                "longitude": lon,
                "altitude": image.get("gpsAltitude", MISSING),
                "altitudeDatum": altitude_datum,
                "source": source,
                "matchedMrk": bool(matched),
                "associationMethod": method,
                "mrkNearest": {
                    "sourceFile": best.get("sourceFile") if best else MISSING,
                    "photoId": best.get("photoId") if best else MISSING,
                    "latitude": best.get("latitude") if best else MISSING,
                    "longitude": best.get("longitude") if best else MISSING,
                    "ellipsoidalHeight": best.get("ellipsoidalHeight") if best else MISSING,
                    "degreeSeparation": best_dist if best_dist is not None else MISSING,
                }
                if best
                else MISSING,
                "sameSessionAsMrk": bool(matched) or same_calendar,
                "association": claim(status, statement, evidence),
            }
        )

    unmatched_mrk = []
    for parsed in mrk_files:
        if parsed.get("fileType") != "djiMrk":
            continue
        rel = parsed.get("relativePath") or parsed.get("filename") or ""
        parent = _parent_key(rel)
        for rec in parsed.get("records") or []:
            photo_id = rec.get("photoId")
            if isinstance(photo_id, int) and (parent, photo_id) not in used_mrk:
                unmatched_mrk.append({"sourceFile": rel, "photoId": photo_id})
    for item in associations:
        item["unmatchedMrkInSameScan"] = unmatched_mrk if item is associations[0] else MISSING
    return associations
