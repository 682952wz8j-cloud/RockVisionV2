from __future__ import annotations

import re
from pathlib import Path

MISSING = "missing"

_RINEX_TYPE = re.compile(r"RINEX VERSION / TYPE\s*$")


def parse_mrk(text: str) -> dict:
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        photo_id = None
        gps_seconds = None
        gps_week = None
        lat = lon = ellh = None
        quality = None
        n_off = e_off = v_off = None
        parts = [p.strip() for p in re.split(r"\t+| {2,}", line) if p.strip()]
        if not parts:
            continue
        try:
            photo_id = int(parts[0].split()[0]) if parts[0][0].isdigit() else None
        except ValueError:
            photo_id = None
        tokens = re.findall(
            r"(-?\d+(?:\.\d+)?)\s*,(Lat|Lon|Ellh|N|E|V|Q)|\[(\d+)\]|(-?\d+(?:\.\d+)?)",
            line,
        )
        labeled = {}
        unlabeled = []
        week = None
        for num, label, bracket, bare in tokens:
            if bracket:
                week = int(bracket)
            elif label:
                labeled[label] = float(num)
            elif bare:
                unlabeled.append(float(bare))
        if "Lat" in labeled:
            lat = labeled["Lat"]
        if "Lon" in labeled:
            lon = labeled["Lon"]
        if "Ellh" in labeled:
            ellh = labeled["Ellh"]
        if "N" in labeled:
            n_off = labeled["N"]
        if "E" in labeled:
            e_off = labeled["E"]
        if "V" in labeled:
            v_off = labeled["V"]
        if "Q" in labeled:
            quality = labeled["Q"]
        if photo_id is not None and len(unlabeled) >= 2:
            gps_seconds = unlabeled[1]
        records.append(
            {
                "photoId": photo_id if photo_id is not None else MISSING,
                "gpsSecondsOfWeek": gps_seconds if gps_seconds is not None else MISSING,
                "gpsWeek": week if week is not None else MISSING,
                "latitude": lat if lat is not None else MISSING,
                "longitude": lon if lon is not None else MISSING,
                "ellipsoidalHeight": ellh if ellh is not None else MISSING,
                "heightDatum": "ellipsoidal" if ellh is not None else MISSING,
                "northOffset": n_off if n_off is not None else MISSING,
                "eastOffset": e_off if e_off is not None else MISSING,
                "verticalOffset": v_off if v_off is not None else MISSING,
                "quality": quality if quality is not None else MISSING,
                "rawLine": line,
            }
        )
    parsed = bool(records) and all(r["latitude"] != MISSING for r in records)
    return {
        "fileType": "djiMrk",
        "parseStatus": "parsed" if parsed else ("partiallyParsed" if records else "unknownFormat"),
        "source": "DJI PPK mark file (photo index, GPS week/seconds, Lat/Lon/Ellh)",
        "recordCount": len(records),
        "records": records,
        "notes": [
            "Ellh is labeled ellipsoidal height in the file.",
            "N/E/V offset units are not stated in-file and are not inferred.",
        ],
    }


def parse_rinex_header(text: str) -> dict:
    header_lines = []
    for line in text.splitlines():
        header_lines.append(line)
        if line[60:].strip() == "END OF HEADER" if len(line) >= 60 else line.strip().endswith("END OF HEADER"):
            break
    fields: dict[str, str] = {}
    for line in header_lines:
        label = line[60:].strip() if len(line) >= 60 else ""
        value = line[:60].rstrip() if len(line) >= 60 else line.rstrip()
        if label:
            fields[label] = value
    version_type = fields.get("RINEX VERSION / TYPE", "")
    file_kind = MISSING
    if "NAV" in version_type.upper():
        file_kind = "rinexNav"
    elif "OBSERVATION" in version_type.upper():
        file_kind = "rinexObs"
    constellations = []
    if "M: Mixed" in version_type or version_type.rstrip().endswith("M"):
        constellations.append("mixed")
    for key, value in fields.items():
        if key.startswith("SYS /"):
            sys_id = value.strip()[:1]
            if sys_id and sys_id not in constellations:
                constellations.append(sys_id)
    epoch_count = sum(1 for line in text.splitlines() if line.startswith(">"))
    return {
        "fileType": file_kind,
        "parseStatus": "parsed" if file_kind != MISSING else "unknownFormat",
        "rinexVersion": version_type.strip()[:20].strip() or MISSING,
        "headerFields": {k: v.strip() for k, v in fields.items()},
        "constellations": constellations or [MISSING],
        "timeOfFirstObs": fields.get("TIME OF FIRST OBS", MISSING),
        "timeOfLastObs": fields.get("TIME OF LAST OBS", MISSING),
        "approxPositionXyz": fields.get("APPROX POSITION XYZ", MISSING),
        "observationEpochCount": epoch_count if file_kind == "rinexObs" else MISSING,
        "notes": [
            "Header parsed from RINEX labels in columns 61–80.",
            "Observation bodies are counted, not fully decoded.",
        ],
    }


def parse_pbk(text: str) -> dict:
    names = [line.strip() for line in text.splitlines() if line.strip()]
    return {
        "fileType": "djiPbkIndex",
        "parseStatus": "partiallyParsed",
        "listedFiles": names,
        "notes": ["PBK contains filenames only; no positions parsed."],
    }


def inspect_rtk_file(path: Path) -> dict:
    ext = path.suffix.lower()
    head = path.read_bytes()[:64]
    rel = path.name
    if ext == ".mrk":
        return {"filename": rel, **parse_mrk(path.read_text(encoding="utf-8", errors="replace"))}
    if ext in {".nav", ".obs", ".rnx", ".rinex"}:
        return {"filename": rel, **parse_rinex_header(path.read_text(encoding="utf-8", errors="replace"))}
    if ext == ".pbk":
        return {"filename": rel, **parse_pbk(path.read_text(encoding="utf-8", errors="replace"))}
    if ext == ".rtk":
        return {
            "filename": rel,
            "fileType": "djiRtkBinary",
            "parseStatus": "unsupported",
            "magic": head[:8].hex(),
            "notes": ["Binary DJI .rtk; no parser in Gate 1B."],
        }
    return {
        "filename": rel,
        "fileType": "unknown",
        "parseStatus": "unknownFormat",
        "notes": ["Extension not mapped to a parser."],
    }
