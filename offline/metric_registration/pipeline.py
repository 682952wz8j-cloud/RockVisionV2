"""COLMAP → WallLocal metric registration. Does not modify incoming, COLMAP, PLY, or DXF."""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from offline.colmap.layout import check_incoming_layout, output_dir as colmap_output_dir, wall_incoming
from offline.ingestion.hashing import snapshot_hashes
from offline.stage2_capability import capability_fields

from .correspondences import build_correspondences, load_json
from .errors import error_stats
from .frames import combine_conditioning, origin_compatible_with_mrk, pointset_geometry
from offline.colmap.source_identity import evaluate_colmap_source_identity

from .height_datum import evaluate_generic_height_from_sources, verify_height_datum
from .positioning_quality import evaluate_positioning_quality_from_sources
from .holdout import split_fit_holdout, split_rule_description
from .ply_crosscheck import landmark_sanity, load_existing_ply, nearest_expanding, write_xyz_ply
from .report import render_report
from .robust import DEFAULT_INLIER_THRESHOLD_M, ransac_umeyama
from .serialize import sim3_payload, write_csv, write_json
from .umeyama import (
    Sim3Error,
    apply_sim3,
    is_proper_rotation as rotation_is_proper,
    matrix4x4_row_major,
    residuals,
    umeyama,
)

INLIER_THRESHOLD_M = DEFAULT_INLIER_THRESHOLD_M
RANSAC_SEED = 20260823
GPS_RUNTIME_POLICY = (
    "MRK/GNSS is used only to compute this offline Sim(3). "
    "Future iPhone visual localization must not use GPS for reference matching, "
    "2D–3D correspondence, PnP, camera pose refinement, or Wall alignment. "
    "GPS may be used only for Wall ID / coarse site selection."
)


def output_dir(root: Path, wall_id: str) -> Path:
    return root / "offline" / "work" / wall_id / "metric_registration"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_log(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _xyz(rows: list[dict], key: str) -> np.ndarray:
    return np.asarray([row[key] for row in rows], dtype=float)


def _scale_sensitivity(fit_src: np.ndarray, fit_dst: np.ndarray, folds: int = 5) -> dict:
    scales = []
    for offset in range(folds):
        keep = [i for i in range(len(fit_src)) if i % folds != offset]
        if len(keep) < 3:
            continue
        try:
            est = umeyama(fit_src[keep], fit_dst[keep])
        except Sim3Error:
            continue
        scales.append(float(est["scale"]))
    if not scales:
        return {"count": 0, "min": None, "median": None, "max": None, "relativeSpread": None, "scales": []}
    arr = np.asarray(scales, dtype=float)
    median = float(np.median(arr))
    spread = float((arr.max() - arr.min()) / median) if median else None
    return {
        "count": int(len(arr)),
        "folds": folds,
        "rule": "fit-set only; leave-one-fold-out by index % 5; Umeyama LS (not RANSAC)",
        "min": float(arr.min()),
        "median": median,
        "max": float(arr.max()),
        "relativeSpread": spread,
        "scales": scales,
    }


def _judge(
    *,
    proper: bool,
    n_corr: int,
    conditioning: str,
    fit_stats: dict,
    hold_stats: dict,
    scale_spread: float | None,
    landmarks: dict,
    ply: dict,
    mixed_datum: bool,
    origin_ok: bool,
    extra_errors: list[str],
    expected_correspondences: int | None = 47,
) -> tuple[str, str, list[str]]:
    problems: list[str] = list(extra_errors)
    if mixed_datum:
        return "NOT VALIDATED", "FAIL", problems + ["Height datum mix or unproven SRSOrigin/Ellh link; STOP"]
    if not origin_ok:
        return "NOT VALIDATED", "FAIL", problems + ["metadata.xml SRSOrigin incompatible with selected MRK (spatial sanity check); STOP"]
    if expected_correspondences is not None and n_corr != expected_correspondences:
        problems.append(f"Expected {expected_correspondences} correspondences, got {n_corr}")
    if not proper:
        return "NOT VALIDATED", "FAIL", problems + ["Sim(3) is not a proper similarity"]
    if landmarks.get("hasNan") or landmarks.get("hasInf") or landmarks.get("kilometerScaleExplosion"):
        return "NOT VALIDATED", "FAIL", problems + ["Transformed landmarks are non-finite or exploded"]
    if conditioning == "DEGENERATE":
        return "NOT VALIDATED", "FAIL", problems + ["Geometry is DEGENERATE; Sim(3) is not reliable"]

    hold_med = hold_stats.get("median")
    fit_med = fit_stats.get("median")
    ply_med = ply.get("median") if ply.get("status") == "ok" else None
    if ply.get("status") == "ok" and ply_med is not None and ply_med > 100:
        problems.append(f"PLY nearest-distance median {ply_med:.3f} m suggests a coordinate-frame conflict")
        return "NOT VALIDATED", "FAIL", problems
    if hold_med is None:
        return "NOT VALIDATED", "FAIL", problems + ["No holdout metrics"]

    # Interpretation vs DJI RTK + unmodeled lever-arm (not a shopped PASS cutoff).
    # Horizontal RTK is centimetre-class; optical-center vs GNSS antenna is unmodeled.
    if hold_med > 5.0:
        problems.append(f"Holdout median 3D error {hold_med:.3f} m is too large for metric use")
        return "NOT VALIDATED", "FAIL", problems
    review = False
    if conditioning == "WEAK":
        problems.append("Geometry conditioning is WEAK")
        review = True
    if scale_spread is not None and scale_spread > 0.15:
        problems.append(f"Scale relative spread {scale_spread:.3f} is unstable")
        review = True
    if fit_med is not None and hold_med > max(2.0, 4.0 * fit_med):
        problems.append("Holdout error is much larger than fit error (possible overfit)")
        review = True
    if hold_stats.get("p90") is not None and hold_stats["p90"] > 3.0:
        problems.append(f"Holdout P90 {hold_stats['p90']:.3f} m is large relative to expected lever-arm")
        review = True
    if ply.get("status") == "ok" and ply_med is not None and ply_med > 10:
        problems.append(f"PLY cross-check median {ply_med:.3f} m is coarse (sparse points may be off-surface)")
        review = True
    if expected_correspondences is not None and n_corr != expected_correspondences:
        review = True
    if review:
        return "NOT VALIDATED", "NEEDS REVIEW", problems
    return "VALIDATED", "PASS", problems


def register(
    wall_id: str,
    root: Path,
    *,
    sources=None,
    dest: Path | None = None,
    colmap_dir: Path | None = None,
) -> dict:
    incoming = wall_incoming(root, wall_id)
    dest = dest or output_dir(root, wall_id)
    dest.mkdir(parents=True, exist_ok=True)
    logs = [f"metric registration start {_now()}", f"wall={wall_id}", GPS_RUNTIME_POLICY]
    errors: list[str] = []

    if sources is None:
        layout_errors = check_incoming_layout(root, wall_id)
        if layout_errors:
            payload = {
                "wallId": wall_id,
                "gateResult": "FAIL",
                "validationStatus": "NOT VALIDATED",
                "errors": layout_errors,
                "problems": layout_errors,
                "incomingUnchanged": True,
            }
            write_json(dest / "metric_registration_metrics.json", payload)
            _write_log(dest / "logs" / "register.log", logs + layout_errors)
            return payload

    before = snapshot_hashes(incoming)
    try:
        payload = _run(
            wall_id,
            root,
            incoming,
            dest,
            logs,
            errors,
            sources=sources,
            colmap_dir=colmap_dir,
        )
    except Exception as exc:
        logs.append(traceback.format_exc())
        payload = {
            "wallId": wall_id,
            "gateResult": "FAIL",
            "validationStatus": "NOT VALIDATED",
            "errors": [f"metric registration exception: {exc}"],
            "problems": [str(exc)],
            "incomingUnchanged": snapshot_hashes(incoming) == before,
        }
        write_json(dest / "metric_registration_metrics.json", payload)
        _write_log(dest / "logs" / "register.log", logs)
        return payload

    after = snapshot_hashes(incoming)
    payload["incomingUnchanged"] = before == after
    if before != after:
        payload["gateResult"] = "FAIL"
        payload["validationStatus"] = "NOT VALIDATED"
        payload.setdefault("problems", []).append("incoming files changed; incoming must remain immutable")
    write_json(dest / "metric_registration_metrics.json", payload)
    (dest / "metric_registration_report.md").write_text(render_report(payload), encoding="utf-8")
    _write_log(dest / "logs" / "register.log", logs + [f"gate={payload.get('gateResult')}"])
    return payload


def _run(
    wall_id: str,
    root: Path,
    incoming: Path,
    dest: Path,
    logs: list[str],
    errors: list[str],
    *,
    sources=None,
    colmap_dir: Path | None = None,
) -> dict:
    generic = sources is not None
    legacy_height = bool(
        generic
        and getattr(sources, "height_sfm_geo_desc", None)
        and getattr(sources, "height_legacy_mrk", None)
    )
    if generic and not legacy_height:
        height = evaluate_generic_height_from_sources(incoming, sources)
        if not height.get("heightGateExecutionAllowed"):
            logs.append(
                f"STOP BEFORE SIM(3): generic height gate "
                f"{height.get('heightVerticalDatumProvenance')} {height.get('reasonCode')}"
            )
            provenance = height.get("heightVerticalDatumProvenance")
            return {
                "wallId": wall_id,
                "gateResult": "FAIL" if provenance == "AUTO_FAIL" else provenance,
                "validationStatus": "NOT VALIDATED",
                "heightDatum": height,
                "heightVerticalDatumProvenance": provenance,
                "heightGateExecutionAllowed": False,
                "reasonCode": height.get("reasonCode"),
                "problems": list(height.get("problems") or [height.get("reasonCode")]),
                "errors": list(height.get("problems") or [height.get("reasonCode")]),
                "correspondenceCount": 0,
                "plyUsedInFit": False,
                **capability_fields(),
                "outputFrame": "WallLocal",
                "wallMetricMetersProvenance": "NOT_CLAIMED",
            }

    positioning = None
    if generic:
        positioning = evaluate_positioning_quality_from_sources(incoming, sources)
        if not positioning.get("positioningQualityExecutionAllowed"):
            logs.append(
                f"STOP BEFORE SIM(3): positioning quality "
                f"{positioning.get('positioningQualityProvenance')} "
                f"{positioning.get('positioningQualityReasonCode')}"
            )
            return {
                "wallId": wall_id,
                "gateResult": positioning.get("positioningQualityProvenance"),
                "validationStatus": "NOT VALIDATED",
                "positioningQuality": positioning,
                "positioningQualityProvenance": positioning.get("positioningQualityProvenance"),
                "positioningQualityReasonCode": positioning.get("positioningQualityReasonCode"),
                "positioningQualityExecutionAllowed": False,
                "reasonCode": positioning.get("positioningQualityReasonCode"),
                "policyVersion": positioning.get("policyVersion"),
                "selectedFrameCount": positioning.get("selectedFrameCount"),
                "fixedFrameCount": positioning.get("fixedFrameCount"),
                "nonFixedFrameCount": positioning.get("nonFixedFrameCount"),
                "missingOrUnparseableFrameCount": positioning.get("missingOrUnparseableFrameCount"),
                "conflictFrameCount": positioning.get("conflictFrameCount"),
                "rtkFlagDistribution": positioning.get("rtkFlagDistribution"),
                "problems": [positioning.get("positioningQualityReasonCode")],
                "errors": [positioning.get("positioningQualityReasonCode")],
                "correspondenceCount": 0,
                "plyUsedInFit": False,
                **capability_fields(),
                "positioningQualityGatePass": False,
                "outputFrame": "WallLocal",
                "wallMetricMetersProvenance": "NOT_CLAIMED",
            }

    from offline.qualification.associate import dji_filename_parts

    colmap_dir = colmap_dir or colmap_output_dir(root, wall_id)
    identity = None
    if generic:
        identity = evaluate_colmap_source_identity(incoming, sources, colmap_dir)
        if not identity.get("colmapSourceIdentityExecutionAllowed"):
            logs.append(
                f"STOP BEFORE SIM(3): COLMAP source identity "
                f"{identity.get('colmapSourceIdentityProvenance')} "
                f"{identity.get('colmapSourceIdentityReasonCode')}"
            )
            provenance = identity.get("colmapSourceIdentityProvenance")
            return {
                "wallId": wall_id,
                "gateResult": "FAIL" if provenance == "AUTO_FAIL" else provenance,
                "validationStatus": "NOT VALIDATED",
                "colmapSourceIdentity": identity,
                "colmapSourceIdentityProvenance": provenance,
                "colmapSourceIdentityReasonCode": identity.get("colmapSourceIdentityReasonCode"),
                "colmapSourceIdentityExecutionAllowed": False,
                "reasonCode": identity.get("colmapSourceIdentityReasonCode"),
                "problems": list(identity.get("problems") or [identity.get("colmapSourceIdentityReasonCode")]),
                "errors": list(identity.get("problems") or [identity.get("colmapSourceIdentityReasonCode")]),
                "correspondenceCount": 0,
                "plyUsedInFit": False,
                **capability_fields(),
                "outputFrame": "WallLocal",
                "wallMetricMetersProvenance": "NOT_CLAIMED",
            }
        sparse_path = Path(identity["resolvedModelPath"])
    else:
        sparse_path = colmap_dir / "sparse" / "0"
        if not (sparse_path / "images.bin").is_file():
            sparse_path = colmap_dir / "sparse" / "best"

    import pycolmap

    if generic:
        images = []
        for rel in sources.image_relative_paths:
            name = Path(rel).name
            parts = dji_filename_parts(name)
            images.append(
                {
                    "relativePath": rel,
                    "filename": name,
                    "mrkPhotoId": parts["sequence"] if parts else None,
                    "mrkAssociationStatus": "PROVEN",
                    "mrkMatched": True,
                }
            )
        manifest = {
            "schemaVersion": "colmap.1",
            "wallId": wall_id,
            "imageCount": len(images),
            "images": images,
            "outputFrame": "WallLocal",
            "wallMetricMetersProvenance": "NOT_CLAIMED",
        }
    else:
        manifest = load_json(colmap_dir / "colmap_source_manifest.json")
    reconstruction = pycolmap.Reconstruction()
    reconstruction.read(str(sparse_path))
    logs.append(f"read COLMAP sparse {sparse_path} images={reconstruction.num_reg_images()} points3D={reconstruction.num_points3D()}")

    corr_kwargs = {}
    if generic:
        corr_kwargs = {
            "mrk_relative_path": sources.mrk_relative_path,
            "metadata_relative_path": sources.metadata_xml_relative_path,
            "require_legacy_session": False,
            "association_method": sources.association_method,
        }
    rows, corr_errors, origin_info = build_correspondences(
        manifest=manifest,
        reconstruction=reconstruction,
        incoming_wall=incoming,
        **corr_kwargs,
    )
    errors.extend(corr_errors)
    association_label = (
        sources.association_method
        if generic
        else "filename_sequence==MRK.photoId + captureSession dji_20260823"
    )
    write_json(
        dest / "camera_correspondences.json",
        {
            "schemaVersion": "camera_correspondences.1",
            "wallId": wall_id,
            "association": association_label,
            "notUsed": ["nearest_coordinate", "nearest_timestamp", "image_order_guess", "lexicographic_first"],
            "count": len(rows),
            "errors": corr_errors,
            "correspondences": rows,
            "outputFrame": "WallLocal",
            "wallMetricMetersProvenance": "NOT_CLAIMED",
        },
    )

    metrics = [np.array([c["projectedMetric"]["easting"], c["projectedMetric"]["northing"], c["projectedMetric"]["ellipsoidalHeight"]]) for c in rows]
    origin = np.array(origin_info["origin"], dtype=float)
    origin_check = origin_compatible_with_mrk(origin, metrics) if metrics else {"compatible": False, "reason": "no correspondences", "semantics": "SPATIAL_SANITY_CHECK", "isCaptureModelProvenanceProof": False}
    if generic:
        if legacy_height:
            height = verify_height_datum(
                incoming,
                origin.tolist(),
                sfm_geo_desc=sources.height_sfm_geo_desc,
                legacy_mrk=sources.height_legacy_mrk,
                require_legacy_proof=True,
            )
        # else: height already decided by evaluate_generic_height_from_sources
    else:
        height = verify_height_datum(incoming, origin.tolist())
    if height["mixedDatumDetected"]:
        errors.extend(height["problems"])
        logs.append("STOP: height datum not proven consistent")
        return {
            "wallId": wall_id,
            "gateResult": "FAIL",
            "validationStatus": "NOT VALIDATED",
            "problems": errors + height["problems"],
            "heightDatum": height,
            "correspondenceCount": len(rows),
        }
    if not origin_check.get("compatible", False):
        errors.append(
            f"SRSOrigin failed spatial sanity check vs selected MRK (max offset {origin_check.get('maxOffsetM')} m); "
            "this is not capture/model provenance proof"
        )
        logs.append("STOP: WallLocal origin incompatible with this MRK session")
        return {
            "wallId": wall_id,
            "gateResult": "FAIL",
            "validationStatus": "NOT VALIDATED",
            "problems": errors,
            "originCompatibility": origin_check,
            "correspondenceCount": len(rows),
        }

    colmap_xyz = _xyz(rows, "colmapCenter")
    wall_xyz = _xyz(rows, "wallLocal")
    colmap_geom = pointset_geometry(colmap_xyz)
    wall_geom = pointset_geometry(wall_xyz)
    conditioning = combine_conditioning(colmap_geom, wall_geom)
    logs.append(f"geometry {conditioning['status']}")

    fit_rows, hold_rows = split_fit_holdout(rows)
    holdout_rule = split_rule_description(n_rows=len(rows))
    write_json(
        dest / "fit_set.json",
        {
            "rule": holdout_rule,
            "count": len(fit_rows),
            "filenames": [r["filename"] for r in fit_rows],
            "mrkPhotoIds": [r["mrkPhotoId"] for r in fit_rows],
        },
    )
    write_json(
        dest / "holdout_set.json",
        {
            "rule": holdout_rule,
            "count": len(hold_rows),
            "filenames": [r["filename"] for r in hold_rows],
            "mrkPhotoIds": [r["mrkPhotoId"] for r in hold_rows],
        },
    )

    fit_src = _xyz(fit_rows, "colmapCenter")
    fit_dst = _xyz(fit_rows, "wallLocal")
    used_ids: list[int] = []
    robust = ransac_umeyama(
        fit_src,
        fit_dst,
        threshold_m=INLIER_THRESHOLD_M,
        seed=RANSAC_SEED,
        used_ids=used_ids,
    )
    if any(i < 0 or i >= len(fit_rows) for i in used_ids):
        raise RuntimeError("RANSAC sampled outside the fit set")
    hold_names = {r["filename"] for r in hold_rows}
    if any(fit_rows[i]["filename"] in hold_names for i in used_ids if i < len(fit_rows)):
        raise RuntimeError("holdout leaked into RANSAC")

    scale = float(robust["scale"])
    rotation = np.asarray(robust["rotation"], dtype=float)
    translation = np.asarray(robust["translation"], dtype=float)
    proper = rotation_is_proper(rotation) and scale > 0 and np.isfinite(scale)
    logs.append(f"Sim3 scale={scale} det={robust['det']} inliers={robust['inlierCount']}")

    inlier_idx = robust["inlierIndices"]
    outlier_idx = robust["outlierIndices"]
    outlier_names = [fit_rows[i]["filename"] for i in outlier_idx]
    fit_res = residuals(fit_src, fit_dst, scale, rotation, translation)
    fit_stats = error_stats(fit_res)
    hold_src = _xyz(hold_rows, "colmapCenter")
    hold_dst = _xyz(hold_rows, "wallLocal")
    hold_pred = apply_sim3(hold_src, scale, rotation, translation)
    hold_res = hold_dst - hold_pred
    hold_stats = error_stats(hold_res)

    holdout_csv_rows = []
    for row, pred, mrk, err in zip(hold_rows, hold_pred, hold_dst, hold_res):
        holdout_csv_rows.append(
            {
                "filename": row["filename"],
                "predicted_x": pred[0],
                "predicted_y": pred[1],
                "predicted_z": pred[2],
                "mrk_x": mrk[0],
                "mrk_y": mrk[1],
                "mrk_z": mrk[2],
                "error_x": err[0],
                "error_y": err[1],
                "error_z": err[2],
                "error_3d": float(np.linalg.norm(err)),
            }
        )
    write_csv(
        dest / "holdout_validation.csv",
        holdout_csv_rows,
        [
            "filename",
            "predicted_x",
            "predicted_y",
            "predicted_z",
            "mrk_x",
            "mrk_y",
            "mrk_z",
            "error_x",
            "error_y",
            "error_z",
            "error_3d",
        ],
    )

    scale_sens = _scale_sensitivity(fit_src, fit_dst)
    write_json(dest / "scale_sensitivity.json", scale_sens)

    points3d = np.asarray(
        [reconstruction.point3D(pid).xyz for pid in reconstruction.point3D_ids()],
        dtype=float,
    )
    transformed = apply_sim3(points3d, scale, rotation, translation)
    land = landmark_sanity(transformed)
    write_xyz_ply(dest / "transformed_sparse_landmarks.ply", transformed)
    write_json(dest / "transformed_sparse_landmarks.json", land)
    logs.append(f"transformed {len(transformed)} landmarks span={land['span']}")

    ply_points, ply_meta = load_existing_ply(
        incoming,
        sources.ply_relative_path if generic else None,
    )
    ply_stats = nearest_expanding(transformed, ply_points)
    ply_stats.update({"ply": ply_meta, "usedInFit": False, "icpApplied": False})
    if land.get("kilometerScaleExplosion") or land.get("hasNan"):
        ply_status = "CONFLICT"
    elif ply_stats.get("status") == "ok" and ply_stats.get("median", 1e9) > 100:
        ply_status = "CONFLICT"
    elif ply_stats.get("status") == "ok":
        ply_status = "OVERLAP_PLAUSIBLE"
    else:
        ply_status = "MISSING"
    ply_stats["crosscheckStatus"] = ply_status
    write_json(dest / "ply_crosscheck.json", ply_stats)
    logs.append(f"PLY cross-check {ply_status} median={ply_stats.get('median')}")

    validation, gate, problems = _judge(
        proper=proper,
        n_corr=len(rows),
        conditioning=conditioning["status"],
        fit_stats=fit_stats,
        hold_stats=hold_stats,
        scale_spread=scale_sens.get("relativeSpread"),
        landmarks=land,
        ply=ply_stats,
        mixed_datum=height["mixedDatumDetected"],
        origin_ok=bool(origin_check.get("compatible")),
        extra_errors=errors,
        expected_correspondences=None if generic else 47,
    )

    sim3 = sim3_payload(
        scale=scale,
        rotation=rotation,
        translation=translation,
        origin=origin_info,
        fit_count=len(fit_rows),
        holdout_count=len(hold_rows),
        inlier_count=robust["inlierCount"],
        threshold_m=INLIER_THRESHOLD_M,
        fit_metrics=fit_stats,
        holdout_metrics=hold_stats,
        solver_meta={"seed": RANSAC_SEED, "iterations": robust["iterations"]},
        created_from={
            "mrk": sources.mrk_relative_path if generic else None,
            "metadataXml": sources.metadata_xml_relative_path if generic else None,
            "colmapSparse": str(sparse_path),
            "outputFrame": "WallLocal",
            "wallMetricMetersProvenance": "NOT_CLAIMED",
            "gpsRuntimeUse": "offline Sim(3) only; GPS must not enter future visual localization / PnP",
        }
        if generic
        else None,
    )
    sim3["status"] = validation
    sim3["gateResult"] = gate
    sim3["gpsRuntimePolicy"] = GPS_RUNTIME_POLICY
    write_json(dest / "S_wall_colmap.json", sim3)

    return {
        "wallId": wall_id,
        "incomingUnchanged": True,
        "validationStatus": validation,
        "gateResult": gate,
        "correspondenceCount": len(rows),
        "fitCount": len(fit_rows),
        "holdoutCount": len(hold_rows),
        "holdoutRule": holdout_rule,
        "conditioning": conditioning,
        "scale": scale,
        "detR": float(robust["det"]),
        "rotation": rotation.tolist(),
        "translation": translation.tolist(),
        "inlierThresholdM": INLIER_THRESHOLD_M,
        "inlierCount": robust["inlierCount"],
        "outlierCount": robust["outlierCount"],
        "outlierFilenames": outlier_names,
        "fitMetrics": fit_stats,
        "holdoutMetrics": hold_stats,
        "scaleSensitivity": scale_sens,
        "plyCrosscheck": ply_stats,
        "landmarks": land,
        "wallLocalOrigin": origin.tolist(),
        "originCompatibility": origin_check,
        "heightDatum": height,
        "heightVerticalDatumProvenance": height.get("heightVerticalDatumProvenance"),
        "heightGateExecutionAllowed": height.get("heightGateExecutionAllowed"),
        "positioningQuality": positioning,
        "positioningQualityProvenance": None if positioning is None else positioning.get("positioningQualityProvenance"),
        "positioningQualityReasonCode": None if positioning is None else positioning.get("positioningQualityReasonCode"),
        "positioningQualityExecutionAllowed": None if positioning is None else positioning.get("positioningQualityExecutionAllowed"),
        "positioningQualityGatePass": False,
        "colmapSourceIdentity": identity,
        "colmapSourceIdentityProvenance": None if identity is None else identity.get("colmapSourceIdentityProvenance"),
        "colmapSourceIdentityReasonCode": None if identity is None else identity.get("colmapSourceIdentityReasonCode"),
        "colmapSourceIdentityExecutionAllowed": None if identity is None else identity.get("colmapSourceIdentityExecutionAllowed"),
        **capability_fields(),
        "problems": problems,
        "errors": errors,
        "matrix4x4": matrix4x4_row_major(scale, rotation, translation),
        "gpsRuntimePolicy": GPS_RUNTIME_POLICY,
        "plyUsedInFit": False,
        "dxfUsedInFit": False,
        "iphoneUsedInFit": False,
        "outputFrame": "WallLocal",
        "wallMetricMetersProvenance": "NOT_CLAIMED",
        "originCompatibilitySemantics": "SPATIAL_SANITY_CHECK",
    }
