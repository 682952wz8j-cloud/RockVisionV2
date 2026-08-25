"""Same-frame Mac rv_pnp ↔ iOS pnpDiagnostic parity. Does not implement a second solver."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import zipfile
from pathlib import Path

import numpy as np

from offline.pnp.constants import (
    CONFIDENCE,
    FLAGS_NAME,
    ITERATIONS_COUNT,
    PINNED_OPENCV_VERSION,
    REPROJECTION_ERROR_NATIVE_PX,
)
from offline.pnp.opencv_cli import load_pinned_pnp
from offline.pnp.pipeline import prepare_frame, run_session

REFINE_REPROJ_WORSE_PX = 1.0
REFINE_CHEIRALITY_DROP = 0.05
ROTATION_DELTA_MAX_DEG = 1.0
C_COLMAP_MAX = 0.313
C_WALL_MAX_M = 1.0
PDR_ONE_EPS = 1e-12
REFINED_REPROJ_ABS_MAX_PX = 8.0
SIM3_SCALE = 3.19764417024824
EXPECTED_SESSION = "gate3d_20260824_171838"
EXPECTED_SCHEMA = "gate3d.runtime.1"
EXPECTED_FRAME_IDS = list(range(39, 59))
DEFAULT_ZIP = Path(
    "/Users/zhengzhang/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
    "xwechat_files/qq404658702_4dbe/msg/file/2026-08/"
    "RockVision_FieldTest_gate3d_20260824_171838.zip"
)


def _finite_num(value) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))


def _finite_vec(values, count: int) -> bool:
    return isinstance(values, (list, tuple)) and len(values) == count and all(_finite_num(v) for v in values)


def _finite_mat(matrix, rows: int, cols: int) -> bool:
    return (
        isinstance(matrix, (list, tuple))
        and len(matrix) == rows
        and all(_finite_vec(row, cols) for row in matrix)
    )


def rodrigues(rvec) -> np.ndarray:
    r = np.asarray(rvec, dtype=float).reshape(3)
    theta = float(np.linalg.norm(r))
    if theta < 1e-16:
        return np.eye(3)
    k = r / theta
    kx, ky, kz = k
    K = np.array([[0.0, -kz, ky], [kz, 0.0, -kx], [-ky, kx, 0.0]])
    return np.eye(3) + math.sin(theta) * K + (1.0 - math.cos(theta)) * (K @ K)


def positive_depth_ratio(object_points, inliers, rotation, tvec) -> float | None:
    if not inliers:
        return None
    R = np.asarray(rotation, dtype=float).reshape(3, 3)
    t = np.asarray(tvec, dtype=float).reshape(3)
    positive = 0
    count = 0
    for idx in inliers:
        if idx < 0 or idx >= len(object_points):
            continue
        xyz = np.asarray(object_points[idx], dtype=float).reshape(3)
        z = float((R @ xyz + t)[2])
        if not math.isfinite(z):
            return None
        count += 1
        if z > 0:
            positive += 1
    if count == 0:
        return None
    return positive / count


def rotation_geodesic_deg(r_mac, r_ios) -> float:
    err = np.asarray(r_mac, dtype=float) @ np.asarray(r_ios, dtype=float).T
    c = max(-1.0, min(1.0, (float(np.trace(err)) - 1.0) * 0.5))
    return math.degrees(math.acos(c))


def chordal_mean_rotation(rotations: list[list[list[float]]]) -> np.ndarray:
    stacked = sum(np.asarray(r, dtype=float) for r in rotations)
    u, _, vt = np.linalg.svd(stacked)
    r = u @ vt
    if np.linalg.det(r) < 0:
        u[:, -1] *= -1
        r = u @ vt
    return r


def percentile(values: list[float], p: float) -> float:
    xs = sorted(values)
    if not xs:
        raise ValueError("empty percentile")
    if p == 50:
        return float(statistics.median(xs))
    k = (len(xs) - 1) * p / 100.0
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return float(xs[lo])
    return float(xs[lo] * (hi - k) + xs[hi] * (k - lo))


def mmx(values: list[float]) -> dict:
    return {"min": min(values), "median": float(statistics.median(values)), "max": max(values)}


def extract_zip(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if EXPECTED_SESSION not in str(zip_path) and not any(EXPECTED_SESSION in n for n in names):
            # Session id is inside session.json, not necessarily the zip member names.
            pass
        zf.extractall(dest)
    samples = dest / "samples.jsonl"
    if not samples.is_file():
        raise FileNotFoundError(f"samples.jsonl missing in {zip_path}")
    return samples


def mac_candidate_qualified(mac: dict, prepared: dict) -> tuple[bool, str | None]:
    if not mac.get("ransacSuccess"):
        return False, "mac_ransacSuccess_false"
    if not mac.get("refineOk"):
        return False, "mac_refineOk_false"
    if not _finite_vec(mac.get("rvecRefined"), 3) or not _finite_vec(mac.get("tvecRefined"), 3):
        return False, "mac_refined_pose_non_finite"
    if not _finite_mat(mac.get("rotationMatrix"), 3, 3) or not _finite_vec(mac.get("C_colmap"), 3):
        return False, "mac_refined_geometry_non_finite"
    if not _finite_mat(mac.get("T_opencvCam_colmap"), 4, 4):
        return False, "mac_T_non_finite"
    ransac_med = (mac.get("reprojectionRansac") or {}).get("median")
    refined_med = (mac.get("reprojectionRefined") or {}).get("median")
    if not _finite_num(ransac_med) or not _finite_num(refined_med):
        return False, "mac_reprojection_non_finite"
    if float(refined_med) > float(ransac_med) + REFINE_REPROJ_WORSE_PX:
        return False, (
            f"mac_refine_reproj_worse refined={refined_med} ransac={ransac_med} "
            f"limit=+{REFINE_REPROJ_WORSE_PX}"
        )
    inliers = [int(i) for i in (mac.get("inliers") or [])]
    r_ransac = rodrigues(mac.get("rvecRansac"))
    pdr_ransac = positive_depth_ratio(prepared["objectPoints"], inliers, r_ransac, mac.get("tvecRansac"))
    pdr_refined = mac.get("positiveDepthRatio")
    if pdr_ransac is None or not _finite_num(pdr_refined):
        return False, "mac_cheirality_non_finite"
    if float(pdr_refined) < float(pdr_ransac) - REFINE_CHEIRALITY_DROP:
        return False, (
            f"mac_cheirality_worse refined={pdr_refined} ransac={pdr_ransac} "
            f"limit=-{REFINE_CHEIRALITY_DROP}"
        )
    for key in ("medianInlierDepthCam", "medianInlierDepthMeters"):
        if not _finite_num(mac.get(key)):
            return False, f"mac_{key}_non_finite"
    if not _finite_vec(mac.get("C_wall"), 3):
        return False, "mac_C_wall_non_finite"
    return True, None


def frame_gate(ios: dict, mac: dict, mac_qualified: bool) -> tuple[bool, str | None]:
    if not ios.get("ransacSuccess"):
        return False, "ios_ransacSuccess_false"
    if not mac.get("ransacSuccess"):
        return False, "mac_ransacSuccess_false"
    if ios.get("candidateQualified") is not True:
        return False, "ios_candidateQualified_false"
    if not mac_qualified:
        return False, "mac_candidateQualified_false"
    rot = rotation_geodesic_deg(mac["rotationMatrix"], ios["rotationMatrix"])
    if rot >= ROTATION_DELTA_MAX_DEG:
        return False, f"rotationDelta={rot} >= {ROTATION_DELTA_MAX_DEG}"
    d_colmap = float(np.linalg.norm(np.asarray(mac["C_colmap"]) - np.asarray(ios["C_colmap"])))
    if d_colmap >= C_COLMAP_MAX:
        return False, f"deltaC_colmap={d_colmap} >= {C_COLMAP_MAX}"
    d_wall = float(np.linalg.norm(np.asarray(mac["C_wall"]) - np.asarray(ios["C_wall"])))
    if d_wall >= C_WALL_MAX_M:
        return False, f"deltaC_wall={d_wall} >= {C_WALL_MAX_M}"
    ios_pdr = ios.get("positiveDepthRatioRefined")
    mac_pdr = mac.get("positiveDepthRatio")
    if abs(float(ios_pdr) - 1.0) > PDR_ONE_EPS:
        return False, f"ios_positiveDepthRatioRefined={ios_pdr} not 1.0"
    if abs(float(mac_pdr) - 1.0) > PDR_ONE_EPS:
        return False, f"mac_positiveDepthRatioRefined={mac_pdr} not 1.0"
    ios_re = (ios.get("reprojectionRefined") or {}).get("median")
    mac_re = (mac.get("reprojectionRefined") or {}).get("median")
    if float(ios_re) > REFINED_REPROJ_ABS_MAX_PX:
        return False, f"ios_refined_reproj={ios_re} > {REFINED_REPROJ_ABS_MAX_PX}"
    if float(mac_re) > REFINED_REPROJ_ABS_MAX_PX:
        return False, f"mac_refined_reproj={mac_re} > {REFINED_REPROJ_ABS_MAX_PX}"
    return True, None


def compare_frame(sample: dict, mac: dict, prepared: dict) -> dict:
    ios = sample["pnpDiagnostic"]
    mac_ok, mac_reason = mac_candidate_qualified(mac, prepared)
    passed, fail_reason = frame_gate(ios, mac, mac_ok)
    if not passed and mac_reason and fail_reason == "mac_candidateQualified_false":
        fail_reason = mac_reason
    rot = rotation_geodesic_deg(mac["rotationMatrix"], ios["rotationMatrix"])
    d_colmap = float(np.linalg.norm(np.asarray(mac["C_colmap"]) - np.asarray(ios["C_colmap"])))
    d_wall = float(np.linalg.norm(np.asarray(mac["C_wall"]) - np.asarray(ios["C_wall"])))
    ios_inl = int(ios["inlierCount"])
    mac_inl = int(mac["inlierCount"])
    ios_ratio = float(ios["inlierRatio"])
    mac_ratio = float(mac["inlierRatio"])
    ios_ransac_re = float((ios.get("reprojectionRansac") or {})["median"])
    mac_ransac_re = float((mac.get("reprojectionRansac") or {})["median"])
    ios_ref_re = float((ios.get("reprojectionRefined") or {})["median"])
    mac_ref_re = float((mac.get("reprojectionRefined") or {})["median"])
    ios_depth = float(ios["medianInlierDepthMeters"])
    mac_depth = float(mac["medianInlierDepthMeters"])
    return {
        "frameID": sample["frameID"],
        "inputCorrespondenceCount": {
            "ios": ios["inputCorrespondenceCount"],
            "mac": mac["inputCorrespondenceCount"],
        },
        "iosRansacSuccess": bool(ios.get("ransacSuccess")),
        "macRansacSuccess": bool(mac.get("ransacSuccess")),
        "iosCandidateQualified": bool(ios.get("candidateQualified")),
        "macCandidateQualified": mac_ok,
        "macCandidateQualifiedReason": mac_reason,
        "iosInlierCount": ios_inl,
        "macInlierCount": mac_inl,
        "inlierCountDelta": mac_inl - ios_inl,
        "iosInlierRatio": ios_ratio,
        "macInlierRatio": mac_ratio,
        "inlierRatioDelta": mac_ratio - ios_ratio,
        "macInlierIndices": mac.get("inliers") or [],
        "iosInlierIndices": "not_exported_in_pnpDiagnostic",
        "iosRansacReprojMedian": ios_ransac_re,
        "macRansacReprojMedian": mac_ransac_re,
        "iosRefinedReprojMedian": ios_ref_re,
        "macRefinedReprojMedian": mac_ref_re,
        "refinedReprojDelta": mac_ref_re - ios_ref_re,
        "iosPositiveDepthRatioRefined": ios.get("positiveDepthRatioRefined"),
        "macPositiveDepthRatioRefined": mac.get("positiveDepthRatio"),
        "rotationDeltaDeg": rot,
        "deltaC_colmap": d_colmap,
        "deltaC_colmapUnits": "colmapReconstruction",
        "deltaC_wall": d_wall,
        "deltaC_wallUnits": "meters",
        "iosMedianInlierDepthMeters": ios_depth,
        "macMedianInlierDepthMeters": mac_depth,
        "observationDepthDeltaMeters": mac_depth - ios_depth,
        "iosLocalizationState": ios.get("localizationState"),
        "pass": passed,
        "failureReason": fail_reason,
    }


def runtime_stability(samples: list[dict]) -> dict:
    diags = [s["pnpDiagnostic"] for s in samples]
    walls = np.asarray([d["C_wall"] for d in diags], dtype=float)
    median_wall = np.median(walls, axis=0)
    displacements = [float(np.linalg.norm(w - median_wall)) for w in walls]
    rotations = [d["rotationMatrix"] for d in diags]
    r_ref = chordal_mean_rotation(rotations)
    vs_mean = [rotation_geodesic_deg(r, r_ref) for r in rotations]
    pairwise = []
    for i in range(len(rotations)):
        for j in range(i + 1, len(rotations)):
            pairwise.append(rotation_geodesic_deg(rotations[i], rotations[j]))
    return {
        "correspondences": mmx([float(d["inputCorrespondenceCount"]) for d in diags]),
        "inliers": mmx([float(d["inlierCount"]) for d in diags]),
        "inlierRatio": mmx([float(d["inlierRatio"]) for d in diags]),
        "refinedReprojMedian": mmx([float((d.get("reprojectionRefined") or {})["median"]) for d in diags]),
        "observationDepthMeters": mmx([float(d["medianInlierDepthMeters"]) for d in diags]),
        "observationDepthNote": "observation-depth sanity, not wallDistance",
        "cWallSpatialDispersion": {
            "definition": "displacement_i = ||C_wall_i - coordinatewise_median(C_wall)||",
            "medianC_wall": median_wall.tolist(),
            "medianC_wallUnits": "meters",
            "medianDisplacementMeters": float(statistics.median(displacements)),
            "p90DisplacementMeters": percentile(displacements, 90),
            "maxDisplacementMeters": max(displacements),
            "name": "C_wall spatial dispersion / camera-center spatial dispersion",
        },
        "orientationDispersion": {
            "definition": (
                "reference = chordal mean of 20 rotation matrices "
                "(SVD of sum R, projected to SO(3)); angles are geodesic "
                "from R_i * R_ref^T in degrees. Pairwise max is max_i<j geodesic(R_i, R_j)."
            ),
            "vsMedianMedianDeg": float(statistics.median(vs_mean)),
            "vsMedianP90Deg": percentile(vs_mean, 90),
            "vsMedianMaxDeg": max(vs_mean),
            "pairwiseMaxDeg": max(pairwise),
        },
    }


def run(zip_path: Path, out_dir: Path, root: Path) -> dict:
    if EXPECTED_SESSION not in zip_path.name:
        raise SystemExit(f"STOP: zip name must contain {EXPECTED_SESSION}, got {zip_path.name}")
    extracted = out_dir / "extracted"
    samples_path = extract_zip(zip_path, extracted)
    session = json.loads((extracted / "session.json").read_text(encoding="utf-8"))
    manifest = json.loads((extracted / "manifest.json").read_text(encoding="utf-8"))
    if session.get("sessionID") != EXPECTED_SESSION:
        raise SystemExit(f"STOP: sessionID={session.get('sessionID')}")
    if manifest.get("schemaVersion") != EXPECTED_SCHEMA:
        raise SystemExit(f"STOP: schema={manifest.get('schemaVersion')}")
    samples = [json.loads(line) for line in samples_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if [s["frameID"] for s in samples] != EXPECTED_FRAME_IDS:
        raise SystemExit(f"STOP: frameIDs={[s['frameID'] for s in samples]}, expected {EXPECTED_FRAME_IDS}")
    for sample in samples:
        n_diag = len(sample.get("diagnosticMatches") or [])
        n_pnp = len(sample.get("pnpCorrespondences") or [])
        if n_pnp <= 20:
            raise SystemExit(f"STOP: frame {sample['frameID']} pnpCorrespondences={n_pnp} looks like diagnostic cap")
        if n_diag != 20:
            raise SystemExit(f"STOP: frame {sample['frameID']} diagnosticMatches={n_diag}")
        prepared = prepare_frame(sample)
        if prepared["inputCorrespondenceCount"] != sample["pnpDiagnostic"]["inputCorrespondenceCount"]:
            raise SystemExit(f"STOP: frame {sample['frameID']} correspondence count mismatch vs iOS diagnostic")

    provenance = load_pinned_pnp(root)
    mac_session = run_session(root, samples_path)
    if mac_session.get("errors"):
        raise SystemExit("STOP: run_session errors: " + "; ".join(mac_session["errors"]))
    mac_by_id = {f["frameID"]: f for f in mac_session["frames"]}
    rows = []
    for sample in samples:
        prepared = prepare_frame(sample)
        mac = mac_by_id[sample["frameID"]]
        rows.append(compare_frame(sample, mac, prepared))
    pass_ids = [r["frameID"] for r in rows if r["pass"]]
    fail_ids = [r["frameID"] for r in rows if not r["pass"]]
    result = "PASS" if len(pass_ids) == 20 and not fail_ids else "FAIL"
    frame49 = next(r for r in rows if r["frameID"] == 49)
    payload = {
        "runtimeSession": EXPECTED_SESSION,
        "schema": EXPECTED_SCHEMA,
        "zipPath": str(zip_path),
        "note163435": (
            "gate3b_20260824_163435 is a different capture / camera placement. "
            "Absolute C_wall(171838)-C_wall(163435) is not a FAIL criterion for this Gate."
        ),
        "macProvenance": {
            "cvVersion": provenance.get("cvVersion"),
            "cli": provenance.get("cli"),
            "importedCv2": provenance.get("importedCv2"),
            "flagsName": provenance.get("flagsName") or FLAGS_NAME,
            "iterationsCount": ITERATIONS_COUNT,
            "reprojectionError": REPROJECTION_ERROR_NATIVE_PX,
            "confidence": CONFIDENCE,
            "status": provenance.get("status"),
            "pinnedOpenCV": PINNED_OPENCV_VERSION,
            "entry": "offline.pnp.pipeline.run_session -> rv_pnp",
        },
        "frozenQualifiedCandidateRule": {
            "ransacSuccess": True,
            "refineOk": True,
            "finite": True,
            "refinedReprojMedianLimit": "ransacMedian + 1.0 px",
            "cheiralityDropLimit": 0.05,
            "note": "pipeline status=ok is not candidateQualified",
        },
        "gateThresholds": {
            "rotationDeltaDeg": ROTATION_DELTA_MAX_DEG,
            "deltaC_colmap": C_COLMAP_MAX,
            "deltaC_colmapUnits": "colmapReconstruction",
            "deltaC_wallMeters": C_WALL_MAX_M,
            "positiveDepthRatioRefined": "abs(x-1.0) <= 1e-12",
            "refinedReprojAbsMaxPx": REFINED_REPROJ_ABS_MAX_PX,
        },
        "runtimeSummary": {
            "independentFrames": len(samples),
            "valid": sum(1 for s in samples if s.get("valid")),
            "invalid": sum(1 for s in samples if not s.get("valid")),
            "iosCandidateQualified": sum(1 for s in samples if s["pnpDiagnostic"].get("candidateQualified")),
            "localization": sorted({s["pnpDiagnostic"].get("localizationState") for s in samples}),
            "openCV": sorted({s["pnpDiagnostic"].get("opencvVersion") for s in samples}),
            "preset": sorted({s.get("presetLabel") for s in samples}),
        },
        "frames": rows,
        "passFrames": pass_ids,
        "failFrames": fail_ids,
        "paritySummary": {
            "rotationDeltaDeg": mmx([r["rotationDeltaDeg"] for r in rows]),
            "deltaC_colmap": mmx([r["deltaC_colmap"] for r in rows]),
            "deltaC_wallMeters": mmx([r["deltaC_wall"] for r in rows]),
            "inlierCountDelta": mmx([float(r["inlierCountDelta"]) for r in rows]),
            "inlierRatioDelta": mmx([r["inlierRatioDelta"] for r in rows]),
            "refinedReprojDelta": mmx([r["refinedReprojDelta"] for r in rows]),
            "observationDepthDeltaMeters": mmx([r["observationDepthDeltaMeters"] for r in rows]),
        },
        "frame49": frame49,
        "runtimeFieldStability": runtime_stability(samples),
        "GATE_3D_VALIDATION_RESULT": result,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "gate3d_runtime_171838_parity.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    csv_headers = [
        "frameID",
        "pass",
        "failureReason",
        "iosCandidateQualified",
        "macCandidateQualified",
        "iosInlierCount",
        "macInlierCount",
        "inlierCountDelta",
        "iosInlierRatio",
        "macInlierRatio",
        "rotationDeltaDeg",
        "deltaC_colmap",
        "deltaC_wall",
        "iosRefinedReprojMedian",
        "macRefinedReprojMedian",
        "iosMedianInlierDepthMeters",
        "macMedianInlierDepthMeters",
        "observationDepthDeltaMeters",
    ]
    lines = [",".join(csv_headers)]
    for row in rows:
        lines.append(",".join(str(row.get(h, "")) for h in csv_headers))
    (out_dir / "gate3d_runtime_171838_parity.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate 3D same-frame Mac ↔ iOS PnP parity")
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output directory (default: offline/work/.../gate3d_runtime_171838)",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.out or (root / "offline" / "work" / "wall_jiulongfeng_01" / "gate3d_runtime_171838")
    payload = run(args.zip, out, root)
    print(f"frames={len(payload['frames'])} pass={len(payload['passFrames'])} fail={payload['failFrames']}")
    print(f"GATE_3D_VALIDATION_RESULT = {payload['GATE_3D_VALIDATION_RESULT']}")
    print(f"wrote {out}")
    return 0 if payload["GATE_3D_VALIDATION_RESULT"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
