"""Terra export-root, spatial-frame, and product selection.

Provenance is NOT geometry ↔ one metadata.xml.
Generic Stage 2 establishes one TerraExportRoot, one TerraSpatialFrame,
and at most one currently approved cross-check-capable deliverable product.

Geometry is not spatial-frame provenance. PLY remains usedInFit=False.
"""

from __future__ import annotations

from pathlib import Path

from offline.ingestion.hashing import sha256_file
from offline.qualification.metadata_scan import parse_model_metadata_xml
from offline.qualification.ply_stats import read_ply_header

from .states import (
    APPROVED_SRS,
    TEMP_PATH_COMPONENT,
    TERRA_CROSSCHECK_PRODUCT_RULE,
    TERRA_EXPORT_ROOT_RULE,
    TERRA_SPATIAL_FRAME_RULE,
    TERRA_TEMP_EXCLUSION_RULE,
    ReasonCode,
    SelectionStatus,
    worst_status,
)

PRODUCT_CATALOG = {
    "terra_point_ply": {
        "productClass": "POINT_CLOUD_PLY",
        "deliverable": True,
        "stage2CrosscheckCapability": True,
    },
    "terra_ply": {
        "productClass": "MESH_PLY",
        "deliverable": True,
        "stage2CrosscheckCapability": True,
    },
    "terra_obj": {
        "productClass": "MESH_OBJ",
        "deliverable": True,
        "stage2CrosscheckCapability": False,
    },
    "terra_las": {
        "productClass": "POINT_CLOUD_LAS",
        "deliverable": True,
        "stage2CrosscheckCapability": False,
    },
    "terra_pnts": {
        "productClass": "POINT_CLOUD_TILES",
        "deliverable": True,
        "stage2CrosscheckCapability": False,
    },
    "terra_b3dms": {
        "productClass": "MESH_TILES",
        "deliverable": True,
        "stage2CrosscheckCapability": False,
    },
}


def has_exact_temp_component(rel: str) -> bool:
    """True iff an exact path component is `.temp`. `temp` / `cache` do not match."""
    if not rel or rel in {".", ""}:
        return False
    return TEMP_PATH_COMPONENT in Path(rel).parts


def _rel(incoming: Path, path: Path) -> str:
    rel = path.relative_to(incoming).as_posix()
    return rel if rel != "." else "."


def _origin_key(origin: list[float]) -> tuple[float, float, float]:
    return (float(origin[0]), float(origin[1]), float(origin[2]))


def _usable_ply(path: Path) -> tuple[bool, dict]:
    try:
        header = read_ply_header(path)
    except OSError as exc:
        return False, {"parseStatus": "unreadable", "error": str(exc)}
    props = [p.split()[-1] for p in header.get("vertexProperties") or []]
    xyz = props[:3] == ["x", "y", "z"]
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
            "comments": header.get("comments"),
        },
    }


def discover_export_roots(incoming: Path) -> list[dict]:
    if not incoming.is_dir():
        return []
    directories = [incoming]
    directories.extend(p for p in incoming.rglob("*") if p.is_dir())
    candidates = []
    for directory in directories:
        rel = _rel(incoming, directory)
        if has_exact_temp_component(rel):
            continue
        tokens = sorted(
            child.name
            for child in directory.iterdir()
            if child.is_dir() and child.name.startswith("terra_")
        )
        if not tokens:
            continue
        report = directory / "report" / "model_report.json"
        sdk = directory / "SDK_Log.txt"
        candidates.append(
            {
                "relativePath": rel,
                "absolutePath": str(directory),
                "terraProductTokens": tokens,
                "supportingEvidence": {
                    "hasModelReport": report.is_file(),
                    "modelReportRelative": _rel(incoming, report) if report.is_file() else None,
                    "hasSdkLog": sdk.is_file(),
                    "sdkLogRelative": _rel(incoming, sdk) if sdk.is_file() else None,
                },
                "rule": TERRA_EXPORT_ROOT_RULE,
                "directoryNameZeroNotRequired": True,
            }
        )
    candidates.sort(key=lambda item: item["relativePath"])
    return candidates


def _parse_metadata_copy(incoming: Path, path: Path) -> dict:
    rel = _rel(incoming, path)
    parsed = parse_model_metadata_xml(path)
    origin = (parsed or {}).get("srsOrigin")
    origin_ok = isinstance(origin, list) and len(origin) == 3
    srs = ((parsed or {}).get("srs") or "").strip() if parsed else None
    if parsed and srs and origin_ok:
        parse_status = "valid"
        reason = None
    elif parsed and not origin_ok:
        parse_status = "malformed"
        reason = "SRSOrigin missing or not exactly three numeric values"
    elif parsed and not srs:
        parse_status = "malformed"
        reason = "SRS missing"
    else:
        parse_status = "malformed"
        reason = "not compatible with ModelMetadata SRS/SRSOrigin"
    return {
        "relativePath": rel,
        "filename": path.name,
        "parentDirectory": Path(rel).parent.as_posix() if Path(rel).parent.as_posix() != "." else ".",
        "sha256": sha256_file(path),
        "parseStatus": parse_status,
        "parsedSRS": srs if parse_status == "valid" else (srs or None),
        "parsedSRSOrigin": _origin_key(origin) if origin_ok else None,
        "srsOriginText": (parsed or {}).get("srsOriginText"),
        "malformedReason": reason,
        "kind": "terraMetadataCopy",
        "isProductIdentity": False,
        "isGeometryIdentity": False,
        "isUniqueGeometryPointer": False,
    }


def select_spatial_frame(incoming: Path, export_root: dict) -> dict:
    root_path = incoming if export_root["relativePath"] == "." else incoming / export_root["relativePath"]
    copies = []
    for path in sorted(root_path.rglob("metadata.xml"), key=lambda p: _rel(incoming, p)):
        if not path.is_file():
            continue
        rel = _rel(incoming, path)
        if has_exact_temp_component(rel):
            continue
        copies.append(_parse_metadata_copy(incoming, path))

    valid = [item for item in copies if item["parseStatus"] == "valid"]
    malformed = [item for item in copies if item["parseStatus"] != "valid"]

    for item in copies:
        item["equivalenceStatus"] = None

    if not valid:
        return {
            "status": SelectionStatus.AUTO_FAIL.value,
            "reasonCode": ReasonCode.NO_VALID_TERRA_METADATA.value,
            "frame": None,
            "copies": copies,
            "malformedCopies": malformed,
            "detail": "No valid ModelMetadata copies under the Terra export root (excluding .temp).",
        }

    if malformed:
        return {
            "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.MALFORMED_TERRA_METADATA_PRESENT.value,
            "frame": None,
            "copies": copies,
            "malformedCopies": malformed,
            "detail": "Valid and malformed metadata copies coexist; malformed copies were not dropped.",
        }

    keys = {(item["parsedSRS"], item["parsedSRSOrigin"]) for item in valid}
    if len(keys) > 1:
        return {
            "status": SelectionStatus.AUTO_FAIL.value,
            "reasonCode": ReasonCode.TERRA_SPATIAL_FRAME_CONFLICT.value,
            "frame": None,
            "copies": copies,
            "malformedCopies": [],
            "detail": "Valid ModelMetadata copies disagree on exact SRS string or parsed SRSOrigin triple.",
        }

    srs, origin = next(iter(keys))
    sha_set = {item["sha256"] for item in valid}
    for item in copies:
        item["equivalenceStatus"] = "equivalent"
    frame = {
        "srs": srs,
        "srsOrigin": list(origin),
        "state": SelectionStatus.AUTO_PASS.value,
        "copyCount": len(valid),
        "copiesByteIdentical": len(sha_set) == 1,
        "byteIdentityRequired": False,
        "textureColorSourceNotPartOfFrame": True,
        "geometryIsNotFrameProvenance": True,
        "originCompatibilityIsNotProvenance": True,
        "rule": TERRA_SPATIAL_FRAME_RULE,
        "evidence": {
            "copyRelativePaths": [item["relativePath"] for item in valid],
            "sha256Values": sorted(sha_set),
        },
    }
    if srs != APPROVED_SRS:
        frame["state"] = SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value
        return {
            "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.UNSUPPORTED_TERRA_SRS.value,
            "frame": frame,
            "copies": copies,
            "malformedCopies": [],
            "detail": (
                f"TerraSpatialFrame SRS is {srs!r}; approved math is {APPROVED_SRS} only. "
                "Do not invent a dynamic CRS."
            ),
        }
    return {
        "status": SelectionStatus.AUTO_PASS.value,
        "reasonCode": ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value,
        "frame": frame,
        "copies": copies,
        "malformedCopies": [],
        "detail": "All valid ModelMetadata copies agree on SRS and parsed SRSOrigin.",
    }


def _discover_product_plies(incoming: Path, product_dir: Path) -> list[dict]:
    found = []
    for path in sorted(product_dir.rglob("*"), key=lambda p: _rel(incoming, p)):
        if not path.is_file() or path.suffix.lower() != ".ply":
            continue
        rel = _rel(incoming, path)
        if has_exact_temp_component(rel):
            continue
        usable, meta = _usable_ply(path)
        record = {
            "relativePath": rel,
            "filename": path.name,
            "parentDirectory": Path(rel).parent.as_posix(),
            "usable": usable,
            "descendantOfProduct": True,
            **meta,
        }
        if usable:
            record["sha256"] = sha256_file(path)
        found.append(record)
    return found


def classify_products(incoming: Path, export_root: dict) -> dict:
    root_path = incoming if export_root["relativePath"] == "." else incoming / export_root["relativePath"]
    products = []
    unknown = []
    intermediates = []
    for child in sorted(root_path.iterdir(), key=lambda p: p.name):
        name = child.name
        if name.lower() == ".ds_store":
            continue
        child_rel = _rel(incoming, child)
        if child.is_dir() and name == TEMP_PATH_COMPONENT:
            ply_intermediates = []
            for path in sorted(child.rglob("*.ply"), key=lambda p: _rel(incoming, p)):
                if path.is_file():
                    ply_intermediates.append(
                        {
                            "relativePath": _rel(incoming, path),
                            "filename": path.name,
                            "fileSize": path.stat().st_size,
                            "classification": "NON_DELIVERABLE_INTERMEDIATE",
                            "rule": TERRA_TEMP_EXCLUSION_RULE,
                        }
                    )
            intermediates.append(
                {
                    "relativePath": child_rel,
                    "classification": "NON_DELIVERABLE_INTERMEDIATE",
                    "rule": TERRA_TEMP_EXCLUSION_RULE,
                    "geometryCandidates": ply_intermediates,
                }
            )
            continue
        if not child.is_dir() or not name.startswith("terra_"):
            continue
        spec = PRODUCT_CATALOG.get(name)
        if spec is None:
            unknown.append(
                {
                    "relativePath": child_rel,
                    "productToken": name,
                    "productClass": "UNKNOWN",
                    "deliverable": False,
                    "stage2CrosscheckCapability": False,
                }
            )
            continue
        geometry = _discover_product_plies(incoming, child) if spec["stage2CrosscheckCapability"] else []
        usable = [item for item in geometry if item.get("usable")]
        products.append(
            {
                "relativePath": child_rel,
                "productToken": name,
                "productClass": spec["productClass"],
                "deliverable": spec["deliverable"],
                "stage2CrosscheckCapability": spec["stage2CrosscheckCapability"],
                "geometryCandidates": geometry,
                "usableGeometryCount": len(usable),
            }
        )
    return {"products": products, "unknown": unknown, "intermediates": intermediates}


def select_crosscheck_product(classified: dict) -> dict:
    if classified["unknown"]:
        return {
            "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.UNKNOWN_TERRA_PRODUCT_TYPE.value,
            "selectedProduct": None,
            "selectedGeometry": None,
            "capable": [],
            "detail": "Unknown terra_* product type present. Do not invent support.",
        }
    capable = []
    ambiguous_geometry = []
    for product in classified["products"]:
        if not product["stage2CrosscheckCapability"] or not product["deliverable"]:
            continue
        usable = [item for item in product["geometryCandidates"] if item.get("usable")]
        if not usable:
            continue
        if len(usable) > 1:
            ambiguous_geometry.append(product)
            continue
        capable.append({**product, "usableGeometry": usable[0]})
    if ambiguous_geometry:
        return {
            "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.MULTIPLE_CROSSCHECK_GEOMETRIES_NO_APPROVED_RANKING.value,
            "selectedProduct": None,
            "selectedGeometry": None,
            "capable": capable,
            "detail": "A cross-check product contains more than one usable PLY. Did not choose first/lexicographic.",
        }
    if not capable:
        return {
            "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.GEOMETRY_CROSSCHECK_NOT_AVAILABLE.value,
            "selectedProduct": None,
            "selectedGeometry": None,
            "capable": [],
            "detail": "No approved cross-check-capable deliverable product with usable geometry.",
        }
    if len(capable) > 1:
        return {
            "status": SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.MULTIPLE_CROSSCHECK_PRODUCTS_NO_APPROVED_RANKING.value,
            "selectedProduct": None,
            "selectedGeometry": None,
            "capable": capable,
            "detail": "Multiple cross-check-capable products. No approved ranking. Did not choose first/lexicographic/size/type.",
        }
    product = capable[0]
    geometry = product["usableGeometry"]
    selected_product = {
        "relativePath": product["relativePath"],
        "productToken": product["productToken"],
        "productClass": product["productClass"],
        "deliverable": True,
        "stage2CrosscheckCapability": True,
        "associationRule": TERRA_CROSSCHECK_PRODUCT_RULE,
    }
    selected_geometry = {
        "relativePath": geometry["relativePath"],
        "filename": geometry["filename"],
        "sha256": geometry.get("sha256"),
        "kind": "modelGeometry",
        "usedInFit": False,
        "productToken": product["productToken"],
        "productClass": product["productClass"],
        "associationRule": TERRA_CROSSCHECK_PRODUCT_RULE,
        "geometryIsNotFrameProvenance": True,
    }
    return {
        "status": SelectionStatus.AUTO_PASS.value,
        "reasonCode": ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value,
        "selectedProduct": selected_product,
        "selectedGeometry": selected_geometry,
        "capable": capable,
        "detail": "Exactly one approved cross-check-capable deliverable product with usable geometry.",
    }


def _representative_copy(copies: list[dict], selected_product: dict | None) -> dict | None:
    valid = [item for item in copies if item.get("parseStatus") == "valid"]
    if not valid:
        return None
    if selected_product:
        prefix = selected_product["relativePath"].rstrip("/") + "/"
        in_product = [item for item in valid if item["relativePath"].startswith(prefix)]
        if len(in_product) == 1:
            return in_product[0]
        if len(in_product) > 1:
            return in_product[0]
    if len(valid) == 1:
        return valid[0]
    return valid[0]


def select_terra_model(incoming: Path, *, frozen_ply_product: dict | None = None) -> dict:
    roots = discover_export_roots(incoming)
    empty = {
        "terraExportRoot": None,
        "terraExportRootEvidence": {
            "rule": TERRA_EXPORT_ROOT_RULE,
            "candidates": roots,
            "directoryNameZeroNotRequired": True,
            "wallIdNotUsed": True,
            "humanFolderNamesNotUsed": True,
        },
        "terraSpatialFrame": None,
        "terraMetadataCopies": [],
        "terraProducts": [],
        "intermediateCandidates": [],
        "selectedCrosscheckProduct": None,
        "selectedCrosscheckGeometry": None,
        "selectedModelSpatialMetadata": None,
        "selectedModelSource": None,
        "uniqueUnprovenModelSpatialMetadata": None,
        "uniqueUnprovenModelGeometry": None,
        "terraPlyProduct": None,
        "modelCandidates": [],
        "modelSpatialMetadataCandidates": [],
        "ambiguous": [],
    }
    if not roots:
        from .ply_product import select_formal_terra_ply_product

        ply_sel = select_formal_terra_ply_product(
            incoming,
            frozen=frozen_ply_product,
            export_roots=roots,
        )
        reason_codes = []
        if ply_sel.get("plyCandidateFound"):
            reason_codes.append(ReasonCode.TERRA_PLY_PRODUCT_NOT_PROVEN.value)
        if ReasonCode.NO_TERRA_EXPORT_ROOT.value not in reason_codes:
            reason_codes.append(ReasonCode.NO_TERRA_EXPORT_ROOT.value)
        if ply_sel.get("reasonCode") and ply_sel["reasonCode"] not in reason_codes:
            reason_codes.insert(0, ply_sel["reasonCode"])
        unique = []
        for code in reason_codes:
            if code not in unique:
                unique.append(code)
        return {
            **empty,
            "terraPlyProduct": ply_sel,
            "status": SelectionStatus.AUTO_FAIL.value,
            "reasonCode": unique[0],
            "reasonCodes": unique,
        }
    if len(roots) > 1:
        return {
            **empty,
            "terraExportRootEvidence": {
                **empty["terraExportRootEvidence"],
                "candidates": roots,
            },
            "status": SelectionStatus.HUMAN_REVIEW_REQUIRED.value,
            "reasonCode": ReasonCode.MULTIPLE_TERRA_EXPORT_ROOTS.value,
            "reasonCodes": [ReasonCode.MULTIPLE_TERRA_EXPORT_ROOTS.value],
            "ambiguous": [{"kind": "terraExportRoot", "relativePath": item["relativePath"]} for item in roots],
            "detail": "Multiple Terra export roots. Did not choose first/lexicographic candidate.",
        }

    root = roots[0]
    frame_result = select_spatial_frame(incoming, root)
    classified = classify_products(incoming, root)
    from .ply_product import select_formal_terra_ply_product

    ply_sel = select_formal_terra_ply_product(
        incoming,
        frozen=frozen_ply_product,
        export_roots=roots,
    )
    copies = frame_result.get("copies") or []
    reason_codes: list[str] = []
    for code in (frame_result.get("reasonCode"), ply_sel.get("reasonCode")):
        if code and code != ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value:
            reason_codes.append(code)
    statuses = [
        SelectionStatus(frame_result["status"]),
        SelectionStatus(ply_sel["status"]),
    ]
    if classified["unknown"]:
        statuses.append(SelectionStatus.DEVELOPMENT_GATE_REVIEW_REQUIRED)
        reason_codes.append(ReasonCode.UNKNOWN_TERRA_PRODUCT_TYPE.value)
    overall = worst_status(statuses)
    if overall == SelectionStatus.AUTO_PASS:
        reason_codes = [ReasonCode.UNIQUE_LEGAL_SOURCE_SET.value]
    elif not reason_codes:
        reason_codes = [overall.value]
    selected_product = None
    selected_geometry = None
    if ply_sel.get("status") == SelectionStatus.AUTO_PASS.value and ply_sel.get("selected"):
        chosen = ply_sel["selected"]
        token = chosen.get("productToken")
        parts = Path(chosen["relativePath"]).parts
        if token in parts:
            product_rel = Path(*parts[: parts.index(token) + 1]).as_posix()
        else:
            product_rel = Path(chosen["relativePath"]).parent.as_posix()
        selected_product = {
            "relativePath": product_rel,
            "productToken": token,
            "productClass": (PRODUCT_CATALOG.get(chosen.get("productToken") or "") or {}).get("productClass"),
            "deliverable": True,
            "stage2CrosscheckCapability": True,
            "associationRule": ply_sel.get("selectionRule"),
        }
        selected_geometry = {
            "relativePath": chosen["relativePath"],
            "filename": chosen["filename"],
            "fileSize": chosen.get("fileSize"),
            "sha256": chosen.get("sha256"),
            "kind": "modelGeometry",
            "usedInFit": False,
            "productToken": chosen.get("productToken"),
            "productClass": selected_product["productClass"],
            "associationRule": ply_sel.get("selectionRule"),
            "geometryIsNotFrameProvenance": True,
            "selected": True,
        }
    if overall != SelectionStatus.AUTO_PASS:
        selected_product = None
        selected_geometry = None

    representative = None
    selected_meta = None
    if frame_result["status"] == SelectionStatus.AUTO_PASS.value and overall == SelectionStatus.AUTO_PASS.value:
        representative = _representative_copy(copies, selected_product)
        if representative:
            selected_meta = {
                "relativePath": representative["relativePath"],
                "filename": representative["filename"],
                "sha256": representative["sha256"],
                "srs": representative["parsedSRS"],
                "srsOrigin": list(representative["parsedSRSOrigin"]),
                "srsOriginText": representative.get("srsOriginText"),
                "associationRule": TERRA_SPATIAL_FRAME_RULE,
                "representativeEquivalentCopy": True,
                "uniquenessIsNotProvenance": True,
                "geometryIsNotFrameProvenance": True,
                "copyCount": len([item for item in copies if item.get("parseStatus") == "valid"]),
            }

    model_candidates = []
    for product in classified["products"]:
        for geom in product.get("geometryCandidates") or []:
            model_candidates.append(
                {
                    "relativePath": geom["relativePath"],
                    "filename": geom["filename"],
                    "parentDirectory": geom.get("parentDirectory"),
                    "sha256": geom.get("sha256"),
                    "kind": "modelGeometry",
                    "productToken": product["productToken"],
                    "usable": geom.get("usable"),
                }
            )

    unique_reasons = []
    for code in reason_codes:
        if code not in unique_reasons:
            unique_reasons.append(code)

    return {
        "status": overall.value,
        "reasonCode": unique_reasons[0] if unique_reasons else None,
        "reasonCodes": unique_reasons,
        "terraExportRoot": {
            "relativePath": root["relativePath"],
            "terraProductTokens": root["terraProductTokens"],
            "rule": TERRA_EXPORT_ROOT_RULE,
        },
        "terraExportRootEvidence": {
            "rule": TERRA_EXPORT_ROOT_RULE,
            "candidates": roots,
            "supportingEvidence": root["supportingEvidence"],
            "directoryNameZeroNotRequired": True,
            "wallIdNotUsed": True,
            "humanFolderNamesNotUsed": True,
        },
        "terraSpatialFrame": frame_result.get("frame"),
        "terraMetadataCopies": copies,
        "terraProducts": classified["products"] + classified["unknown"],
        "intermediateCandidates": classified["intermediates"],
        "selectedCrosscheckProduct": selected_product,
        "selectedCrosscheckGeometry": selected_geometry,
        "selectedModelSpatialMetadata": selected_meta,
        "selectedModelSource": selected_geometry,
        "uniqueUnprovenModelSpatialMetadata": None,
        "uniqueUnprovenModelGeometry": None,
        "modelCandidates": model_candidates,
        "modelSpatialMetadataCandidates": copies,
        "terraPlyProduct": ply_sel,
        "ambiguous": [
            *([{"kind": "terraMetadataCopy", **item} for item in frame_result.get("malformedCopies") or []]),
            *(
                [
                    {"kind": "terraPlyProduct", "relativePath": item["relativePath"]}
                    for item in (ply_sel.get("candidates") or [])
                    if item.get("rejectedReason") == ReasonCode.TERRA_PLY_PRODUCT_AMBIGUOUS.value
                ]
                if ply_sel.get("reasonCode") == ReasonCode.TERRA_PLY_PRODUCT_AMBIGUOUS.value
                else []
            ),
        ],
        "frameStatus": frame_result["status"],
        "frameReasonCode": frame_result["reasonCode"],
        "crosscheckStatus": ply_sel.get("status"),
        "crosscheckReasonCode": ply_sel.get("reasonCode"),
        "unknownTerraProductTypes": classified["unknown"],
    }
