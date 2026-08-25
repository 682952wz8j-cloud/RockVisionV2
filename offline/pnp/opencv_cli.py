"""Pin + invoke rv_pnp. Never import cv2."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from offline.ingestion.hashing import sha256_file
from offline.reference_matching.constants import PINNED_OPENCV_COMMIT, PINNED_OPENCV_VERSION
from offline.reference_matching.opencv_env import OpenCVProvenanceError, pin_paths, verify_ios_pins

from .constants import FLAGS_NAME, REPROJECTION_ERROR_NATIVE_PX


def pnp_cli(root: Path) -> Path:
    return pin_paths(root)["vendor"] / "bin" / "rv_pnp"


def calib3d_dylib(root: Path) -> Path:
    return pin_paths(root)["installLib"] / "libopencv_calib3d.4.14.0.dylib"


def load_pinned_pnp(root: Path) -> dict:
    pins = verify_ios_pins(root)
    cli = pnp_cli(root)
    dylib = calib3d_dylib(root)
    if not cli.is_file():
        raise OpenCVProvenanceError("STOP: rv_pnp missing; build offline/pnp/pnp.cpp against opencv414")
    if not dylib.is_file():
        raise OpenCVProvenanceError("STOP: pinned libopencv_calib3d.4.14.0.dylib missing")
    env = os.environ.copy()
    env.pop("DYLD_LIBRARY_PATH", None)
    result = subprocess.run([str(cli), "--version"], env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise OpenCVProvenanceError(f"STOP: rv_pnp --version failed: {result.stderr}")
    cv_version = None
    for line in result.stdout.splitlines():
        if line.startswith("cvVersion="):
            cv_version = line.split("=", 1)[1].strip()
    if cv_version != PINNED_OPENCV_VERSION:
        raise OpenCVProvenanceError(f"STOP: rv_pnp cvVersion={cv_version}")
    if "5.0.0" in result.stdout or "site-packages" in result.stdout:
        raise OpenCVProvenanceError("STOP: rv_pnp version output looks like system cv2")
    return {
        "cvVersion": cv_version,
        "commit": pins["commit"],
        "cli": str(cli.resolve()),
        "calib3d": str(dylib.resolve()),
        "cliSha256": sha256_file(cli),
        "importedCv2": False,
        "flagsName": FLAGS_NAME,
        "reprojectionError": REPROJECTION_ERROR_NATIVE_PX,
        "status": "PINNED_SOURCE_MATCH",
        "sourceCommit": PINNED_OPENCV_COMMIT,
        "versionOutput": result.stdout,
    }


def run_self_test(root: Path) -> dict:
    runtime = load_pinned_pnp(root)
    cli = Path(runtime["cli"])
    env = os.environ.copy()
    env.pop("DYLD_LIBRARY_PATH", None)
    result = subprocess.run([str(cli), "--self-test"], env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise OpenCVProvenanceError(f"STOP: rv_pnp --self-test failed: {result.stderr or result.stdout}")
    payload = json.loads(result.stdout)
    if payload.get("importedCv2"):
        raise OpenCVProvenanceError("STOP: self-test claimed cv2 import")
    if payload.get("cvVersion") != PINNED_OPENCV_VERSION:
        raise OpenCVProvenanceError("STOP: self-test cvVersion is not 4.14.0")
    if not payload.get("pass"):
        raise OpenCVProvenanceError("STOP: convention self-test did not pass")
    payload["runtime"] = runtime
    return payload


def write_request(path: Path, object_points, image_points, fx: float, fy: float, cx: float, cy: float) -> None:
    if len(object_points) != len(image_points):
        raise OpenCVProvenanceError("STOP: object/image count mismatch")
    lines = [str(len(object_points))]
    for xyz, uv in zip(object_points, image_points):
        lines.append(f"{xyz[0]} {xyz[1]} {xyz[2]} {uv[0]} {uv[1]}")
    lines.append(f"{fx} {fy} {cx} {cy}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def solve(root: Path, request_path: Path, result_path: Path) -> dict:
    runtime = load_pinned_pnp(root)
    cli = Path(runtime["cli"])
    env = os.environ.copy()
    env.pop("DYLD_LIBRARY_PATH", None)
    result = subprocess.run(
        [str(cli), "--solve", "--in", str(request_path), "--out", str(result_path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result_path.is_file():
        raise OpenCVProvenanceError(f"STOP: rv_pnp --solve failed: {result.stderr or result.stdout}")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if payload.get("cvVersion") != PINNED_OPENCV_VERSION:
        raise OpenCVProvenanceError("STOP: solve cvVersion is not 4.14.0")
    if payload.get("importedCv2"):
        raise OpenCVProvenanceError("STOP: solve claimed cv2 import")
    payload["runtime"] = {k: runtime[k] for k in ("cvVersion", "cli", "importedCv2", "flagsName")}
    return payload
