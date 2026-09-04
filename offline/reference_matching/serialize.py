"""RVS1 descriptors.bin + sidecar provenance. Not a Wall Package."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

from offline.ingestion.hashing import sha256_file
from offline.metric_registration.umeyama import apply_sim3

from .constants import (
    ARTIFACT_SCHEMA,
    DESCRIPTOR_DIM,
    LANDMARKS_SCHEMA,
    RVS1_DTYPE_FLOAT32,
    RVS1_MAGIC,
    RVS1_VERSION,
)


class ArtifactError(ValueError):
    pass


def write_rvs1(path: Path, descriptors: np.ndarray) -> None:
    desc = np.asarray(descriptors, dtype=np.float32)
    if desc.ndim != 2:
        raise ArtifactError(f"descriptors must be 2D, got {desc.shape}")
    if desc.shape[1] != DESCRIPTOR_DIM:
        raise ArtifactError(f"descriptor dim {desc.shape[1]} != {DESCRIPTOR_DIM}")
    if not np.isfinite(desc).all():
        raise ArtifactError("non-finite descriptors")
    path.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack(
        "<4sIIII",
        RVS1_MAGIC,
        RVS1_VERSION,
        RVS1_DTYPE_FLOAT32,
        DESCRIPTOR_DIM,
        int(desc.shape[0]),
    )
    path.write_bytes(header + desc.astype("<f4", copy=False).tobytes(order="C"))


def read_rvs1(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if len(data) < 20:
        raise ArtifactError("truncated RVS1 header")
    magic, version, dtype, dim, count = struct.unpack_from("<4sIIII", data, 0)
    if magic != RVS1_MAGIC:
        raise ArtifactError(f"bad magic {magic!r}")
    if version != RVS1_VERSION:
        raise ArtifactError(f"unsupported RVS1 version {version}")
    if dtype != RVS1_DTYPE_FLOAT32:
        raise ArtifactError(f"unsupported dtype {dtype}")
    if dim != DESCRIPTOR_DIM:
        raise ArtifactError(f"descriptor dim {dim} != {DESCRIPTOR_DIM}")
    expected = 20 + count * dim * 4
    if len(data) != expected:
        raise ArtifactError(f"RVS1 length {len(data)} != {expected}")
    desc = np.frombuffer(data, dtype="<f4", offset=20).reshape(count, dim).copy()
    if not np.isfinite(desc).all():
        raise ArtifactError("non-finite descriptors")
    return desc


def apply_s_wall_colmap(colmap_xyz: np.ndarray, sim3: dict) -> np.ndarray:
    rotation = np.asarray(sim3["rotationMatrix"]["values"], dtype=float)
    translation = np.asarray(sim3["translationMeters"], dtype=float)
    scale = float(sim3["scale"])
    return apply_sim3(colmap_xyz, scale, rotation, translation)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def freeze_artifact(
    dest: Path,
    *,
    wall_id: str,
    descriptors: np.ndarray,
    rows: list[dict],
    reference_images: list[dict],
    association_report: dict,
    database_stats: dict,
    opencv_provenance: dict,
    sim3: dict,
    extra: dict | None = None,
    production_bound: bool = False,
    wall_build_run_id: str | None = None,
    colmap_model_fingerprint: str | None = None,
) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    desc_path = dest / "descriptors.bin"
    landmarks_path = dest / "landmarks.json"
    write_rvs1(desc_path, descriptors)
    if len(rows) != len(descriptors):
        raise ArtifactError("landmarks length != descriptor rows")
    if production_bound:
        if not wall_build_run_id or not colmap_model_fingerprint:
            raise ArtifactError("production-bound freeze requires verified runId and modelFingerprint")
    landmarks = {
        "schema": LANDMARKS_SCHEMA,
        "schemaId": ARTIFACT_SCHEMA,
        "wallId": wall_id,
        "developmentFixtureOnly": not production_bound,
        "notAWallPackage": not production_bound,
        "xyzFrameId": "colmap_reconstruction_rhs_opencv_units",
        "sift": database_stats.get("sift"),
        "matchingHints": {
            "knnK": 16,
            "ratioThreshold": 0.8,
            "distanceType": "l2",
            "matchUnit": "unique_point3d",
            "minDistinctPoint3DForRatio": 2,
            "candidateK": 16,
        },
        "referenceImages": reference_images,
        "landmarks": rows,
        "sWallColmap": {
            "status": sim3.get("status"),
            "name": sim3.get("name"),
            "convention": sim3.get("convention"),
            "usedExistingValidatedSim3": True,
        },
        "opencv": opencv_provenance,
        "matcherHotPath": ["descriptor", "point3DID"],
        "xyzNotUsedInMatching": True,
    }
    landmarks_path.write_text(json.dumps(landmarks, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    write_json(dest / "association_report.json", association_report)
    write_json(dest / "database_stats.json", database_stats)
    freeze = {
        "artifactDirectory": str(dest),
        "descriptorsPath": "descriptors.bin",
        "landmarksPath": "landmarks.json",
        "descriptorCount": int(len(descriptors)),
        "descriptorsSha256": sha256_file(desc_path),
        "landmarksSha256": sha256_file(landmarks_path),
        "descriptorsBytes": int(desc_path.stat().st_size),
        "landmarksBytes": int(landmarks_path.stat().st_size),
        "wallId": wall_id,
        **(extra or {}),
    }
    # Verified Stage 2 identity always wins over caller extra.
    if wall_build_run_id:
        freeze["wallBuildRunId"] = wall_build_run_id
    if colmap_model_fingerprint:
        freeze["colmapModelFingerprint"] = colmap_model_fingerprint
    write_json(dest / "freeze.json", freeze)
    return freeze


def load_frozen(dest: Path) -> dict:
    freeze_path = dest / "freeze.json"
    if not freeze_path.is_file():
        raise ArtifactError(f"missing freeze.json in {dest}")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    desc_path = dest / "descriptors.bin"
    landmarks_path = dest / "landmarks.json"
    if sha256_file(desc_path) != freeze["descriptorsSha256"]:
        raise ArtifactError("descriptors.bin SHA-256 does not match freeze.json")
    if sha256_file(landmarks_path) != freeze["landmarksSha256"]:
        raise ArtifactError("landmarks.json SHA-256 does not match freeze.json")
    descriptors = read_rvs1(desc_path)
    landmarks = json.loads(landmarks_path.read_text(encoding="utf-8"))
    rows = landmarks["landmarks"]
    if len(rows) != len(descriptors):
        raise ArtifactError("frozen landmarks count != descriptor rows")
    point3d = np.asarray([int(r["point3DID"]) for r in rows], dtype=np.int64)
    image_ids = np.asarray([int(r["referenceImageID"]) for r in rows], dtype=np.int64)
    return {
        "freeze": freeze,
        "landmarks": landmarks,
        "descriptors": descriptors,
        "point3dIds": point3d,
        "imageIds": image_ids,
        "rows": rows,
    }
