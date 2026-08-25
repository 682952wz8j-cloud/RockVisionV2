"""CLI-only OpenCV 4.14.0 provenance. Never import cv2."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from offline.ingestion.hashing import sha256_file

from .constants import PINNED_OPENCV_COMMIT, PINNED_OPENCV_TAG, PINNED_OPENCV_VERSION

IOS_PIN_DIR = Path("ios") / "Vendor" / "OpenCV"
VENDOR_DIR = Path("offline") / "vendor" / "opencv414"
REQUIRED_DYLIBS = (
    "libopencv_core.4.14.0.dylib",
    "libopencv_imgproc.4.14.0.dylib",
    "libopencv_imgcodecs.4.14.0.dylib",
    "libopencv_features2d.4.14.0.dylib",
    "libopencv_flann.4.14.0.dylib",
)


class OpenCVProvenanceError(RuntimeError):
    pass


def pin_paths(root: Path) -> dict[str, Path]:
    pin = root / IOS_PIN_DIR
    vendor = root / VENDOR_DIR
    return {
        "versionTxt": pin / "VERSION.txt",
        "sourceCommitTxt": pin / "SOURCE_COMMIT.txt",
        "sourceClone": pin / "opencv",
        "vendor": vendor,
        "cli": vendor / "bin" / "rv_sift_extract",
        "installLib": vendor / "install" / "lib",
        "provenance": vendor / "PROVENANCE.json",
    }


def read_ios_pins(root: Path) -> dict:
    paths = pin_paths(root)
    if not paths["sourceCommitTxt"].is_file() or not paths["versionTxt"].is_file():
        raise OpenCVProvenanceError("iOS OpenCV pin files are missing")
    commit = paths["sourceCommitTxt"].read_text(encoding="utf-8").strip()
    version = None
    tag = None
    for line in paths["versionTxt"].read_text(encoding="utf-8").splitlines():
        if line.startswith("version:"):
            version = line.split(":", 1)[1].strip()
        if line.startswith("tag:"):
            tag = line.split(":", 1)[1].strip()
    return {"commit": commit, "version": version, "tag": tag, "paths": paths}


def _git_head(clone: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise OpenCVProvenanceError(f"STOP: cannot read OpenCV source HEAD: {result.stderr}")
    return result.stdout.strip()


def verify_ios_pins(root: Path) -> dict:
    pins = read_ios_pins(root)
    errors: list[str] = []
    if pins["commit"] != PINNED_OPENCV_COMMIT:
        errors.append(f"SOURCE_COMMIT.txt is {pins['commit']}, expected {PINNED_OPENCV_COMMIT}")
    if pins["version"] != PINNED_OPENCV_VERSION:
        errors.append(f"VERSION.txt version is {pins['version']}, expected {PINNED_OPENCV_VERSION}")
    if pins["tag"] != PINNED_OPENCV_TAG:
        errors.append(f"VERSION.txt tag is {pins['tag']}, expected {PINNED_OPENCV_TAG}")
    clone = pins["paths"]["sourceClone"]
    if not (clone / ".git").exists():
        errors.append("pinned OpenCV source clone missing")
    else:
        head = _git_head(clone)
        pins["sourceCloneHead"] = head
        if head != PINNED_OPENCV_COMMIT:
            errors.append(f"ios/Vendor/OpenCV/opencv HEAD is {head}, expected {PINNED_OPENCV_COMMIT}")
    if errors:
        raise OpenCVProvenanceError("STOP: " + "; ".join(errors))
    return pins


def _otool_l(cli: Path) -> str:
    result = subprocess.run(["otool", "-L", str(cli)], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise OpenCVProvenanceError(f"STOP: otool -L failed: {result.stderr}")
    return result.stdout


def _otool_load(cli: Path) -> str:
    result = subprocess.run(["otool", "-l", str(cli)], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise OpenCVProvenanceError(f"STOP: otool -l failed: {result.stderr}")
    return result.stdout


def _rpath_values(otool_l_text: str) -> list[str]:
    paths: list[str] = []
    lines = otool_l_text.splitlines()
    for i, line in enumerate(lines):
        if "LC_RPATH" in line:
            for follow in lines[i + 1 : i + 4]:
                stripped = follow.strip()
                if stripped.startswith("path "):
                    paths.append(stripped.split("path ", 1)[1].split(" (", 1)[0].strip())
                    break
    return paths


def _opencv_otool_deps(otool_L_text: str) -> list[str]:
    deps = []
    for line in otool_L_text.splitlines()[1:]:
        name = line.strip().split(" ", 1)[0]
        if "libopencv_" in name:
            deps.append(name)
    return deps


def _cli_version(cli: Path) -> tuple[str, str]:
    result = subprocess.run([str(cli), "--version"], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise OpenCVProvenanceError(f"STOP: {cli} --version failed: {result.stderr}")
    cv_version = None
    for line in result.stdout.splitlines():
        if line.startswith("cvVersion="):
            cv_version = line.split("=", 1)[1].strip()
    if cv_version is None:
        raise OpenCVProvenanceError(f"STOP: {cli} did not print cvVersion")
    return cv_version, result.stdout


def _first_dji_image(root: Path) -> Path:
    incoming = root / "incoming" / "wall_jiulongfeng_01"
    matches = sorted(p for p in incoming.rglob("*.JPG") if p.is_file())
    if not matches:
        raise OpenCVProvenanceError("STOP: no DJI JPG for provenance extraction")
    return matches[0]


def _runtime_extract_proof(cli: Path, image: Path, out: Path) -> dict:
    env = os.environ.copy()
    env.pop("DYLD_LIBRARY_PATH", None)
    env["DYLD_PRINT_LIBRARIES"] = "1"
    if out.exists():
        out.unlink()
    result = subprocess.run([str(cli), str(image), str(out)], env=env, capture_output=True, text=True)
    if result.returncode != 0 or not out.is_file():
        raise OpenCVProvenanceError(
            f"STOP: rv_sift_extract runtime extraction failed: {result.stderr or result.stdout}"
        )
    loaded = []
    for line in (result.stderr or "").splitlines():
        if "libopencv_" in line:
            loaded.append(line.strip())
    return {
        "image": str(image),
        "output": str(out),
        "stdout": result.stdout,
        "dyldPrintLibraries": loaded,
        "bytes": int(out.stat().st_size),
    }


def collect_cli_provenance(root: Path) -> dict:
    pins = verify_ios_pins(root)
    paths = pin_paths(root)
    cli = paths["cli"]
    install_lib = paths["installLib"]
    source = paths["sourceClone"]
    if not cli.is_file():
        raise OpenCVProvenanceError("STOP: rv_sift_extract missing")
    if not install_lib.is_dir():
        raise OpenCVProvenanceError("STOP: pinned OpenCV install/lib missing")
    head = pins.get("sourceCloneHead") or _git_head(source)
    if head != PINNED_OPENCV_COMMIT:
        raise OpenCVProvenanceError(f"STOP: source HEAD {head} != {PINNED_OPENCV_COMMIT}")
    cv_version, version_text = _cli_version(cli)
    if cv_version != PINNED_OPENCV_VERSION:
        raise OpenCVProvenanceError(f"STOP: CLI cvVersion={cv_version}, expected {PINNED_OPENCV_VERSION}")
    otool_L = _otool_l(cli)
    otool_l = _otool_load(cli)
    rpaths = _rpath_values(otool_l)
    expected_rpath = str(install_lib.resolve())
    if expected_rpath not in rpaths:
        raise OpenCVProvenanceError(
            f"STOP: LC_RPATH does not include {expected_rpath}; got {rpaths}"
        )
    deps = _opencv_otool_deps(otool_L)
    if not deps:
        raise OpenCVProvenanceError("STOP: otool -L has no libopencv_ dependencies")
    for dep in deps:
        if "site-packages" in dep or dep.startswith("/usr/local") or "5.0" in dep:
            raise OpenCVProvenanceError(f"STOP: otool -L opencv dep is not pinned: {dep}")
        if not dep.startswith("@rpath/libopencv_"):
            raise OpenCVProvenanceError(f"STOP: opencv dep is not @rpath: {dep}")
    dylib_paths = {name: install_lib / name for name in REQUIRED_DYLIBS}
    missing = [name for name, path in dylib_paths.items() if not path.is_file()]
    if missing:
        raise OpenCVProvenanceError(f"STOP: missing pinned dylibs {missing}")
    smoke = paths["vendor"] / "provenance_smoke.rve1"
    proof = _runtime_extract_proof(cli, _first_dji_image(root), smoke)
    loaded_files = []
    for line in proof["dyldPrintLibraries"]:
        if ".dylib" in line:
            token = line.split(":")[-1].strip() if ":" in line else line
            for part in token.split():
                if "libopencv_" in part:
                    loaded_files.append(part)
    resolved_loaded = []
    for item in loaded_files:
        path = Path(item)
        if path.exists():
            resolved_loaded.append(str(path.resolve()))
    expected_resolved = {str((install_lib / name).resolve()) for name in REQUIRED_DYLIBS}
    if resolved_loaded:
        bad = [p for p in resolved_loaded if p not in expected_resolved]
        if bad:
            raise OpenCVProvenanceError(f"STOP: runtime loaded non-pinned OpenCV dylibs {bad}")
        if not (expected_resolved & set(resolved_loaded)):
            raise OpenCVProvenanceError("STOP: runtime did not load pinned libopencv_*.4.14.0.dylib")
    return {
        "cvVersion": cv_version,
        "source_commit": head,
        "sourceCommit": head,
        "sourceTag": PINNED_OPENCV_TAG,
        "source_repo_path": str(source.resolve()),
        "rv_sift_extract_path": str(cli.resolve()),
        "opencv_dylib_paths": {name: str(path.resolve()) for name, path in dylib_paths.items()},
        "cliSha256": sha256_file(cli),
        "dylibSha256": {name: sha256_file(path) for name, path in dylib_paths.items()},
        "otoolL": otool_L,
        "otoolLOpenCVDeps": deps,
        "otoolRpath": rpaths,
        "installLib": expected_rpath,
        "versionOutput": version_text,
        "runtimeExtraction": proof,
        "binding": "mac-cli-linked-to-pinned-dylibs",
        "importedCv2": False,
        "status": "PINNED_SOURCE_MATCH",
    }


def write_cli_provenance(root: Path) -> dict:
    payload = collect_cli_provenance(root)
    path = pin_paths(root)["provenance"]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def verify_stored_cli_provenance(root: Path) -> dict:
    pins = verify_ios_pins(root)
    paths = pin_paths(root)
    cli = paths["cli"]
    install_lib = paths["installLib"]
    if not paths["provenance"].is_file():
        raise OpenCVProvenanceError("STOP: PROVENANCE.json missing")
    stored = json.loads(paths["provenance"].read_text(encoding="utf-8"))
    if stored.get("cv2File") or stored.get("cvVersion") == "5.0.0" or stored.get("importedCv2"):
        raise OpenCVProvenanceError("STOP: stale provenance pointing at Python cv2; rewrite CLI provenance")
    head = pins.get("sourceCloneHead")
    if head != PINNED_OPENCV_COMMIT:
        raise OpenCVProvenanceError(f"STOP: source HEAD {head} != {PINNED_OPENCV_COMMIT}")
    if stored.get("source_commit") != PINNED_OPENCV_COMMIT and stored.get("sourceCommit") != PINNED_OPENCV_COMMIT:
        raise OpenCVProvenanceError("STOP: PROVENANCE.json source commit is not the pin")
    cv_version, version_text = _cli_version(cli)
    if cv_version != PINNED_OPENCV_VERSION:
        raise OpenCVProvenanceError(f"STOP: CLI cvVersion={cv_version}")
    live_sha = sha256_file(cli)
    if live_sha != stored.get("cliSha256"):
        raise OpenCVProvenanceError("STOP: rv_sift_extract SHA-256 does not match PROVENANCE.json")
    otool_L = _otool_l(cli)
    rpaths = _rpath_values(_otool_load(cli))
    expected_rpath = str(install_lib.resolve())
    if expected_rpath not in rpaths:
        raise OpenCVProvenanceError(f"STOP: LC_RPATH does not include {expected_rpath}; got {rpaths}")
    deps = _opencv_otool_deps(otool_L)
    if not deps or any(not d.startswith("@rpath/libopencv_") for d in deps):
        raise OpenCVProvenanceError(f"STOP: otool -L opencv deps not pinned @rpath: {deps}")
    for name in REQUIRED_DYLIBS:
        path = install_lib / name
        if not path.is_file():
            raise OpenCVProvenanceError(f"STOP: missing {path}")
        expected = (stored.get("dylibSha256") or {}).get(name)
        if expected and sha256_file(path) != expected:
            raise OpenCVProvenanceError(f"STOP: {name} SHA-256 does not match PROVENANCE.json")
    proof = stored.get("runtimeExtraction") or {}
    if int(proof.get("bytes") or 0) <= 0:
        raise OpenCVProvenanceError("STOP: PROVENANCE.json has no runtime extraction proof")
    return {
        "cvVersion": cv_version,
        "tag": PINNED_OPENCV_TAG,
        "commit": PINNED_OPENCV_COMMIT,
        "cli": str(cli.resolve()),
        "status": "PINNED_SOURCE_MATCH",
        "sourceCloneHead": head,
        "iosPinCommit": pins["commit"],
        "iosPinVersion": pins["version"],
        "iosPinTag": pins["tag"],
        "binding": "mac-cli-linked-to-pinned-dylibs",
        "provenance": stored,
        "importedCv2": False,
        "versionOutput": version_text,
    }


def load_pinned_opencv(root: Path) -> dict:
    """Verify CLI provenance and return the rv_sift_extract path. Does not import cv2."""
    return verify_stored_cli_provenance(root)


def provenance_payload(root: Path) -> dict:
    try:
        return load_pinned_opencv(root)
    except OpenCVProvenanceError as exc:
        try:
            pins = verify_ios_pins(root)
        except OpenCVProvenanceError as pin_exc:
            return {"status": "STOP", "error": str(pin_exc)}
        return {
            "iosPinCommit": pins["commit"],
            "iosPinVersion": pins["version"],
            "iosPinTag": pins["tag"],
            "sourceCloneHead": pins.get("sourceCloneHead"),
            "status": "STOP",
            "error": str(exc),
        }
