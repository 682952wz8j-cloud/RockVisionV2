from __future__ import annotations

import json


def _dumps(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def render_report(payload: dict) -> str:
    fit = payload.get("fitMetrics") or {}
    hold = payload.get("holdoutMetrics") or {}
    scale = payload.get("scaleSensitivity") or {}
    ply = payload.get("plyCrosscheck") or {}
    lines = [
        "# Metric Registration Report — S_wall_colmap",
        "",
        f"Wall ID: {payload.get('wallId')}",
        f"Incoming immutable: {'PASS' if payload.get('incomingUnchanged') else 'FAIL'}",
        f"S_wall_colmap: {payload.get('validationStatus')}",
        f"Gate result: {payload.get('gateResult')}",
        "",
        "## Coordinate frames",
        "",
        "- COLMAP `C`: sparse reconstruction world. Pose is world-to-camera `x_cam = R x_world + t`. Center `C = -R^T t`.",
        "- MRK geodetic `G`: 2026-08-23 latitude / longitude / **Ellh = ellipsoidal height** (not orthometric, not MSL, not local Z).",
        "- Projected metric `M`: EPSG:32650 easting/northing + Ellh. This is **not** a complete 3D EPSG:32650 CRS.",
        "- WallLocal `W`: metres, `W = M - SRSOrigin`. Translation only; no axis swap or ENU rotation.",
        f"- WallLocal origin: {payload.get('wallLocalOrigin')}",
        "",
        "## Correspondences",
        "",
        f"valid pairs: {payload.get('correspondenceCount')} (filename sequence == MRK photoId, session dji_20260823)",
        f"fit / holdout: {payload.get('fitCount')} / {payload.get('holdoutCount')}",
        f"holdout rule: {(payload.get('holdoutRule') or {}).get('rule')}",
        "",
        "## Geometry conditioning",
        "",
        _dumps(payload.get("conditioning")),
        "",
        "## Sim(3)",
        "",
        f"scale: {payload.get('scale')}  →  1 COLMAP unit = {payload.get('scale')} m",
        f"det(R): {payload.get('detR')}",
        f"translation (WallLocal metres): {payload.get('translation')}",
        "convention: X_wall = s * R * X_colmap + t",
        "",
        "## Robust fit",
        "",
        f"threshold: {payload.get('inlierThresholdM')} m (a priori; not loosened to force 47/47)",
        f"inliers / outliers: {payload.get('inlierCount')} / {payload.get('outlierCount')}",
        f"outlier filenames: {payload.get('outlierFilenames')}",
        f"fit 3D median / P90 / max / RMSE: {fit.get('median')} / {fit.get('p90')} / {fit.get('max')} / {fit.get('rmse')}",
        "",
        "## Independent holdout",
        "",
        f"holdout cameras: {payload.get('holdoutCount')}",
        f"3D median / mean / P90 / max / RMSE: {hold.get('median')} / {hold.get('mean')} / {hold.get('p90')} / {hold.get('max')} / {hold.get('rmse')}",
        f"horizontal median / P90 / max: {(hold.get('horizontal') or {}).get('median')} / {(hold.get('horizontal') or {}).get('p90')} / {(hold.get('horizontal') or {}).get('max')}",
        f"vertical median / P90 / max: {(hold.get('vertical') or {}).get('median')} / {(hold.get('vertical') or {}).get('p90')} / {(hold.get('vertical') or {}).get('max')}",
        "",
        "## Scale sensitivity (fit subsets only)",
        "",
        _dumps(scale),
        "",
        "## Transformed landmarks vs PLY (cross-check only; not used in fit)",
        "",
        _dumps(ply),
        "",
        "## Height datum",
        "",
        "Z is DJI MRK ellipsoidal height. SRSOrigin Z was re-checked against sfm_geo_desc.ref_GPS / legacy MRK Ellh 352.504.",
        "No geoid offset was applied.",
        "",
        "## GPS runtime policy",
        "",
        "MRK/GNSS is used only to compute this offline Sim(3). Future iPhone visual localization must not use GPS for matching, 2D–3D, PnP, or wall alignment.",
        "",
        "## Problems",
        "",
    ]
    problems = payload.get("problems") or []
    if problems:
        lines.extend(f"- {item}" for item in problems)
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)
