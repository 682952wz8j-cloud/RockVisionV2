"""Field Test sidecar → offline PnP. Official pose is T_opencvCam_colmap only."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import numpy as np

from offline.metric_registration.serialize import load_sim3
from offline.reference_matching.serialize import apply_s_wall_colmap

from .constants import (
    CAMERA_CENTER_CONVENTION,
    DISTORTION_MODEL,
    EXPECTED_NATIVE_HEIGHT,
    EXPECTED_NATIVE_WIDTH,
    FORBIDDEN_FIELD_TEST,
    POSE_CONVENTION,
    POSE_NAME,
    QUERY_COORDINATE_SPACE,
)
from .opencv_cli import solve, write_request


class PnPPipelineError(RuntimeError):
    pass


def _finite_xyz(xyz) -> bool:
    if not isinstance(xyz, (list, tuple)) or len(xyz) != 3:
        return False
    return all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in xyz)


def prepare_frame(sample: dict) -> dict:
    correspondences = sample.get("pnpCorrespondences") or []
    seen = set()
    object_points = []
    image_points = []
    kept = []
    xyz_missing = 0
    duplicate = 0
    for row in correspondences:
        pid = row.get("point3DID")
        if pid in seen:
            duplicate += 1
            continue
        seen.add(pid)
        space = row.get("queryCoordinateSpace")
        if space != QUERY_COORDINATE_SPACE:
            raise PnPPipelineError(f"STOP: queryCoordinateSpace is {space!r}, expected {QUERY_COORDINATE_SPACE}")
        xyz = row.get("colmapXYZ")
        if not _finite_xyz(xyz):
            xyz_missing += 1
            continue
        uv = row.get("queryXYNative") or []
        if len(uv) != 2 or not all(math.isfinite(float(v)) for v in uv):
            xyz_missing += 1
            continue
        object_points.append([float(xyz[0]), float(xyz[1]), float(xyz[2])])
        image_points.append([float(uv[0]), float(uv[1])])
        kept.append(row)
    sidecar_missing = int(sample.get("xyzMissingRejected") or xyz_missing)
    if sidecar_missing != xyz_missing and sample.get("xyzMissingRejected") is not None:
        # Count from correspondences is source of truth for PnP input; record both.
        pass
    camera = sample.get("cameraSidecar") or {}
    return {
        "frameID": sample.get("frameID"),
        "scene": sample.get("scene"),
        "objectPoints": object_points,
        "imagePoints": image_points,
        "inputCorrespondenceCount": len(object_points),
        "xyzMissingRejected": xyz_missing,
        "duplicatePoint3DRejected": duplicate,
        "acceptedUniquePoint3D": sample.get("acceptedUniquePoint3D"),
        "camera": camera,
        "sampleXyzMissingRejected": sample.get("xyzMissingRejected"),
        "sampleInputCorrespondenceCount": sample.get("inputCorrespondenceCount"),
    }


def _assert_native_k(camera: dict) -> list[str]:
    errors = []
    if camera.get("queryCoordinateSpace") != QUERY_COORDINATE_SPACE:
        errors.append(f"camera queryCoordinateSpace is {camera.get('queryCoordinateSpace')}")
    if camera.get("distortionModel") != DISTORTION_MODEL:
        errors.append(f"distortionModel is {camera.get('distortionModel')}")
    if not camera.get("imageResolutionMatchesCaptured"):
        errors.append("imageResolution does not match capturedImage")
    if camera.get("capturedWidth") != EXPECTED_NATIVE_WIDTH or camera.get("capturedHeight") != EXPECTED_NATIVE_HEIGHT:
        errors.append(
            f"capturedImage is {camera.get('capturedWidth')}x{camera.get('capturedHeight')}, expected {EXPECTED_NATIVE_WIDTH}x{EXPECTED_NATIVE_HEIGHT}"
        )
    if camera.get("imageResolutionWidth") != EXPECTED_NATIVE_WIDTH or camera.get("imageResolutionHeight") != EXPECTED_NATIVE_HEIGHT:
        errors.append("imageResolution is not 1920x1440")
    if not camera.get("pnpIntrinsicsReady", False):
        errors.append("pnpIntrinsicsReady is false")
    return errors


def apply_c_wall(c_colmap: list[float], sim3: dict) -> list[float]:
    xyz = apply_s_wall_colmap(np.asarray([c_colmap], dtype=float), sim3)
    return xyz[0].tolist()


def solve_frame(root: Path, prepared: dict, sim3: dict | None) -> dict:
    camera = prepared["camera"]
    k_errors = _assert_native_k(camera)
    payload = {
        "frameID": prepared["frameID"],
        "scene": prepared["scene"],
        "inputCorrespondenceCount": prepared["inputCorrespondenceCount"],
        "xyzMissingRejected": prepared["xyzMissingRejected"],
        "duplicatePoint3DRejected": prepared["duplicatePoint3DRejected"],
        "poseName": POSE_NAME,
        "poseConvention": POSE_CONVENTION,
        "cameraCenterConvention": CAMERA_CENTER_CONVENTION,
        "intrinsicsErrors": k_errors,
        "status": "ok",
    }
    if k_errors:
        payload["status"] = "STOP"
        payload["error"] = "; ".join(k_errors)
        return payload
    if prepared["inputCorrespondenceCount"] < 4:
        payload["status"] = "insufficientCorrespondences"
        payload["ransacSuccess"] = False
        return payload
    fx = float(camera["fx"])
    fy = float(camera["fy"])
    cx = float(camera["cx"])
    cy = float(camera["cy"])
    with tempfile.TemporaryDirectory() as tmp:
        request = Path(tmp) / "request.txt"
        result = Path(tmp) / "result.json"
        write_request(request, prepared["objectPoints"], prepared["imagePoints"], fx, fy, cx, cy)
        solved = solve(root, request, result)
    payload.update(solved)
    if sim3 is not None and solved.get("C_colmap"):
        payload["C_wall"] = apply_c_wall(solved["C_colmap"], sim3)
        scale = float(sim3.get("scale") or 0)
        payload["medianInlierDepthMeters"] = float(solved.get("medianInlierDepthCam") or 0) * scale
        payload["S_wall_colmap"] = {
            "path": str(sim3.get("_path") or ""),
            "status": sim3.get("status") or sim3.get("validationStatus"),
            "scale": scale,
            "name": sim3.get("name"),
        }
        payload["observationDepthNote"] = "medianInlierDepthMeters is observation depth sanity, not wallDistance"
    return payload


def load_samples(path: Path) -> list[dict]:
    samples = []
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        for line in text.splitlines():
            if line.strip():
                samples.append(json.loads(line))
        return samples
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    return payload.get("samples") or []


def run_session(root: Path, samples_path: Path, wall_id: str = "wall_jiulongfeng_01") -> dict:
    if FORBIDDEN_FIELD_TEST in samples_path.as_posix():
        raise PnPPipelineError(f"STOP: {FORBIDDEN_FIELD_TEST} is Gate 3C control only, not Gate 3D correctness input")
    samples = load_samples(samples_path)
    sim3_path = root / "offline" / "work" / wall_id / "metric_registration" / "S_wall_colmap.json"
    sim3 = None
    if sim3_path.is_file():
        sim3 = load_sim3(sim3_path)
        sim3["_path"] = str(sim3_path)
    frames = []
    errors = []
    for sample in samples:
        prepared = prepare_frame(sample)
        if sample.get("scene") == "A" and prepared["xyzMissingRejected"] > 0:
            errors.append(f"Scene A frame {sample.get('frameID')} xyzMissingRejected={prepared['xyzMissingRejected']}")
        frames.append(solve_frame(root, prepared, sim3))
    a_frames = [f for f in frames if f.get("scene") == "A"]
    if any(f.get("status") == "STOP" for f in a_frames):
        errors.append("Scene A has native K / coordinate STOP")
    return {
        "samplesPath": str(samples_path),
        "wallId": wall_id,
        "frameCount": len(frames),
        "frames": frames,
        "errors": errors,
        "gate": "3D",
        "forbiddenFieldTest": FORBIDDEN_FIELD_TEST,
    }
