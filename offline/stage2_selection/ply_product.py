"""Formal Terra reconstruction PLY product selection.

Finding a .ply is not product identity. Selection uses Terra export-root
structure and model_report.json generate flags. Filesystem order, mtime,
and size are not selection keys.
"""

from __future__ import annotations

import json
from pathlib import Path

from offline.ingestion.hashing import sha256_file
from offline.qualification.ply_stats import read_ply_header

from .states import (
    TEMP_PATH_COMPONENT,
    TERRA_PLY_PRODUCT_RULE,
    ReasonCode,
    SelectionStatus,
)

SCHEMA_VERSION = "terra_ply_product.1"
FORMAL_PLY_TOKENS = ("terra_point_ply", "terra_ply")
REPORT_FLAG_TO_TOKEN = {
    "generate point ply": "terra_point_ply",
    "generate ply": "terra_ply",
}


def has_exact_temp_component(rel: str) -> bool:
    if not rel or rel in {".", ""}:
        return False
    return TEMP_PATH_COMPONENT in Path(rel).parts


def _rel(incoming: Path, path: Path) -> str:
    rel = path.relative_to(incoming).as_posix()
    return rel if rel != "." else "."


def _product_token_for(rel: str) -> str | None:
    parts = Path(rel).parts
    for part in parts:
        if part in FORMAL_PLY_TOKENS or part.startswith("terra_"):
            return part
    return None


def _usable_ply(path: Path) -> tuple[bool, dict]:
    try:
        header = read_ply_header(path)
    except OSError as exc:
        return False, {"parseStatus": "unreadable", "error": str(exc)}
    props = [p.split()[-1] for p in header.get("vertexProperties") or []]
    xyz = "x" in props and "y" in props and "z" in props
    vertices = int(header.get("vertexCount") or 0)
    if vertices < 1 or not xyz:
        return False, {
            "parseStatus": "malformed",
            "header": {
                "format": header.get("format"),
                "vertexCount": vertices,
                "faceCount": header.get("faceCount"),
                "vertexProperties": header.get("vertexProperties"),
            },
        }
    return True, {
        "parseStatus": "ok",
        "header": {
            "format": header.get("format"),
            "vertexCount": vertices,
            "faceCount": header.get("faceCount"),
            "vertexProperties": header.get("vertexProperties"),
        },
    }


def discover_ply_candidates(incoming: Path) -> list[dict]:
    """All .ply files under incoming, sorted by relative path. Order is provenance only."""
    if not incoming.is_dir():
        return []
    found = []
    for path in incoming.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".ply":
            continue
        rel = _rel(incoming, path)
        usable, meta = _usable_ply(path)
        under_temp = has_exact_temp_component(rel)
        token = _product_token_for(rel)
        record = {
            "relativePath": rel,
            "filename": path.name,
            "parentDirectory": Path(rel).parent.as_posix() if Path(rel).parent.as_posix() != "." else ".",
            "fileSize": path.stat().st_size,
            "sha256": None,
            "plyCandidateFound": True,
            "underTemp": under_temp,
            "productToken": token,
            "usable": usable,
            "selected": False,
            "rejectedReason": None,
            **meta,
        }
        if usable and not under_temp:
            record["sha256"] = sha256_file(path)
        found.append(record)
    found.sort(key=lambda item: item["relativePath"])
    return found


def read_model_report_ply_flags(export_root_path: Path) -> dict | None:
    report = export_root_path / "report" / "model_report.json"
    if not report.is_file():
        return None
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    flags = {}
    for key, token in REPORT_FLAG_TO_TOKEN.items():
        value = payload.get(key)
        flags[token] = value is True
    return {
        "relativePath": report.name,
        "reportRelative": None,
        "generatePly": bool(payload.get("generate ply") is True),
        "generatePointPly": bool(payload.get("generate point ply") is True),
        "declaredTokens": [token for token, enabled in flags.items() if enabled],
    }


def _identify_products(incoming: Path, export_root: dict | None, candidates: list[dict]) -> dict:
    if not export_root:
        return {
            "terraProductIdentified": False,
            "identifiedProductTokens": [],
            "identificationEvidence": {
                "rule": TERRA_PLY_PRODUCT_RULE,
                "modelReportUsed": False,
                "fallbackUsed": False,
                "detail": "No unique Terra export root.",
            },
        }
    root_path = incoming if export_root["relativePath"] == "." else incoming / export_root["relativePath"]
    flags = read_model_report_ply_flags(root_path)
    if flags is not None:
        flags["reportRelative"] = str(Path(export_root["relativePath"]) / "report" / "model_report.json")
        if export_root["relativePath"] == ".":
            flags["reportRelative"] = "report/model_report.json"
        tokens = list(flags["declaredTokens"])
        return {
            "terraProductIdentified": bool(tokens),
            "identifiedProductTokens": tokens,
            "identificationEvidence": {
                "rule": TERRA_PLY_PRODUCT_RULE,
                "modelReportUsed": True,
                "fallbackUsed": False,
                "modelReportRelative": flags["reportRelative"],
                "generatePly": flags["generatePly"],
                "generatePointPly": flags["generatePointPly"],
                "detail": "Formal PLY product tokens taken from model_report.json generate flags.",
            },
        }
    present = []
    for token in FORMAL_PLY_TOKENS:
        if any(
            item.get("productToken") == token and item.get("usable") and not item.get("underTemp")
            for item in candidates
        ):
            present.append(token)
    present = sorted(set(present))
    return {
        "terraProductIdentified": len(present) > 0,
        "identifiedProductTokens": present,
        "identificationEvidence": {
            "rule": TERRA_PLY_PRODUCT_RULE,
            "modelReportUsed": False,
            "fallbackUsed": True,
            "detail": (
                "No readable model_report.json; fallback is unique terra_ply / "
                "terra_point_ply directory that already contains usable geometry."
            ),
        },
    }


def _formal_match(item: dict, identified_tokens: list[str]) -> bool:
    if item.get("underTemp"):
        return False
    if not item.get("usable"):
        return False
    token = item.get("productToken")
    if token not in identified_tokens:
        return False
    return True


def _reject_reason(item: dict, identified_tokens: list[str], formal: list[dict]) -> str | None:
    if item.get("underTemp"):
        return "NON_DELIVERABLE_INTERMEDIATE"
    if not item.get("usable"):
        return "PLY_NOT_USABLE"
    token = item.get("productToken")
    if not identified_tokens:
        return "TERRA_PLY_PRODUCT_NOT_PROVEN"
    if token not in identified_tokens:
        return "NOT_DECLARED_FORMAL_TERRA_PLY_PRODUCT"
    if item in formal and len(formal) > 1:
        return "TERRA_PLY_PRODUCT_AMBIGUOUS"
    return None


def _empty_record(
    *,
    status: str,
    reason: str,
    candidates: list[dict],
    identified: dict,
    formal: list[dict] | None = None,
) -> dict:
    formal = formal or []
    tokens = identified.get("identifiedProductTokens") or []
    for item in candidates:
        item["selected"] = False
        item["rejectedReason"] = _reject_reason(item, tokens, formal)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "plyCandidateFound": bool(candidates),
        "plyCandidateCount": len(candidates),
        "candidates": candidates,
        "terraProductIdentified": bool(identified.get("terraProductIdentified")),
        "identifiedProductTokens": list(identified.get("identifiedProductTokens") or []),
        "identificationEvidence": identified.get("identificationEvidence") or {},
        "terraProductUnambiguous": False,
        "terraProductSelected": False,
        "terraProductProvenanceRecorded": True,
        "selected": None,
        "status": status,
        "reasonCode": reason,
        "frozen": False,
        "selectionRule": TERRA_PLY_PRODUCT_RULE,
    }


def select_formal_terra_ply_product(
    incoming: Path,
    *,
    frozen: dict | None = None,
    candidates: list[dict] | None = None,
    export_roots: list[dict] | None = None,
) -> dict:
    """Select the unique formal Terra reconstruction PLY, or fail closed.

    `candidates` may be a permutation of discovered PLYs; selection ignores order.
    `frozen` short-circuits live discovery and preserves a materialized run identity.
    """
    if frozen:
        payload = dict(frozen)
        payload["frozen"] = True
        payload["terraProductProvenanceRecorded"] = True
        return payload

    from .terra import discover_export_roots

    roots = list(export_roots) if export_roots is not None else discover_export_roots(incoming)
    discovered = list(candidates) if candidates is not None else discover_ply_candidates(incoming)
    discovered.sort(key=lambda item: item["relativePath"])

    if len(roots) > 1:
        identified = _identify_products(incoming, None, discovered)
        record = _empty_record(
            status=SelectionStatus.HUMAN_REVIEW_REQUIRED.value,
            reason=ReasonCode.MULTIPLE_TERRA_EXPORT_ROOTS.value,
            candidates=discovered,
            identified=identified,
        )
        return record
    if len(roots) == 0:
        identified = _identify_products(incoming, None, discovered)
        if discovered:
            return _empty_record(
                status=SelectionStatus.AUTO_FAIL.value,
                reason=ReasonCode.TERRA_PLY_PRODUCT_NOT_PROVEN.value,
                candidates=discovered,
                identified=identified,
            )
        return _empty_record(
            status=SelectionStatus.AUTO_FAIL.value,
            reason=ReasonCode.NO_TERRA_EXPORT_ROOT.value,
            candidates=discovered,
            identified=identified,
        )

    root = roots[0]
    identified = _identify_products(incoming, root, discovered)
    tokens = list(identified.get("identifiedProductTokens") or [])
    formal = [item for item in discovered if _formal_match(item, tokens)]
    formal.sort(key=lambda item: item["relativePath"])

    if not discovered:
        return _empty_record(
            status=SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            reason=ReasonCode.GEOMETRY_CROSSCHECK_NOT_AVAILABLE.value,
            candidates=discovered,
            identified=identified,
        )

    if not tokens:
        return _empty_record(
            status=SelectionStatus.AUTO_FAIL.value,
            reason=ReasonCode.TERRA_PLY_PRODUCT_NOT_PROVEN.value,
            candidates=discovered,
            identified=identified,
        )

    if len(formal) > 1:
        return _empty_record(
            status=SelectionStatus.AUTO_FAIL.value,
            reason=ReasonCode.TERRA_PLY_PRODUCT_AMBIGUOUS.value,
            candidates=discovered,
            identified=identified,
            formal=formal,
        )

    if len(formal) == 0:
        return _empty_record(
            status=SelectionStatus.AUTO_FAIL.value,
            reason=ReasonCode.TERRA_PLY_PRODUCT_NOT_PROVEN.value,
            candidates=discovered,
            identified=identified,
        )

    chosen = formal[0]
    for item in discovered:
        if item["relativePath"] == chosen["relativePath"]:
            item["selected"] = True
            item["rejectedReason"] = None
        else:
            item["selected"] = False
            item["rejectedReason"] = _reject_reason(item, tokens, [chosen])

    selected = {
        "relativePath": chosen["relativePath"],
        "filename": chosen["filename"],
        "fileSize": chosen["fileSize"],
        "sha256": chosen["sha256"],
        "productToken": chosen["productToken"],
        "selected": True,
        "selectionRule": TERRA_PLY_PRODUCT_RULE,
        "evidence": {
            "identifiedProductTokens": tokens,
            "modelReportUsed": bool((identified.get("identificationEvidence") or {}).get("modelReportUsed")),
            "fallbackUsed": bool((identified.get("identificationEvidence") or {}).get("fallbackUsed")),
            "candidateCount": len(discovered),
        },
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "plyCandidateFound": True,
        "plyCandidateCount": len(discovered),
        "candidates": discovered,
        "terraProductIdentified": True,
        "identifiedProductTokens": tokens,
        "identificationEvidence": identified.get("identificationEvidence") or {},
        "terraProductUnambiguous": True,
        "terraProductSelected": True,
        "terraProductProvenanceRecorded": True,
        "selected": selected,
        "status": SelectionStatus.AUTO_PASS.value,
        "reasonCode": ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value,
        "frozen": False,
        "selectionRule": TERRA_PLY_PRODUCT_RULE,
    }
