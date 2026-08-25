"""DJI native-resolution OpenCV SIFT. Uses pinned OpenCV 4.14.0 CLI only."""

from __future__ import annotations

import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .constants import DESCRIPTOR_DIM, GRAYSCALE_NOTE, SIFT_CONTRAST_THRESHOLD, SIFT_EDGE_THRESHOLD, SIFT_N_OCTAVE_LAYERS, SIFT_NFEATURES, SIFT_SIGMA
from .opencv_env import OpenCVProvenanceError, load_pinned_opencv


@dataclass
class ExtractedImage:
    image_id: int
    name: str
    path: Path
    width: int
    height: int
    xy: np.ndarray
    descriptors: np.ndarray
    keypoint_count: int
    cache: Path | None = None


def read_rve1_header(path: Path) -> tuple[int, int, int]:
    data = path.read_bytes()[:24]
    if len(data) < 24 or data[:4] != b"RVE1":
        raise RuntimeError(f"bad RVE1 header in {path}")
    version, width, height, count, dim = struct.unpack_from("<IIIII", data, 4)
    if version != 1 or dim != DESCRIPTOR_DIM:
        raise RuntimeError(f"unexpected RVE1 version/dim {version}/{dim}")
    return int(width), int(height), int(count)


def read_rve1(path: Path) -> tuple[int, int, np.ndarray, np.ndarray]:
    data = path.read_bytes()
    if len(data) < 24 or data[:4] != b"RVE1":
        raise RuntimeError(f"bad RVE1 header in {path}")
    version, width, height, count, dim = struct.unpack_from("<IIIII", data, 4)
    if version != 1 or dim != DESCRIPTOR_DIM:
        raise RuntimeError(f"unexpected RVE1 version/dim {version}/{dim}")
    offset = 24
    xy_bytes = count * 2 * 8
    desc_bytes = count * dim * 4
    expected = offset + xy_bytes + desc_bytes
    if len(data) != expected:
        raise RuntimeError(f"RVE1 length {len(data)} != {expected}")
    xy = np.frombuffer(data, dtype="<f8", count=count * 2, offset=offset).reshape(count, 2).copy()
    desc = np.frombuffer(data, dtype="<f4", count=count * dim, offset=offset + xy_bytes).reshape(count, dim).copy()
    if not np.isfinite(desc).all():
        raise RuntimeError("non-finite SIFT descriptors")
    return int(width), int(height), xy, desc


def extract_reference_image(cli: Path, image_path: Path, *, image_id: int, name: str, dest: Path) -> ExtractedImage:
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = dest.with_suffix(".rve1")
    result = subprocess.run([str(cli), str(image_path), str(raw)], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"rv_sift_extract failed for {image_path}: {result.stderr or result.stdout}")
    width, height, xy, desc = read_rve1(raw)
    return ExtractedImage(
        image_id=image_id,
        name=name,
        path=image_path,
        width=width,
        height=height,
        xy=xy,
        descriptors=desc,
        keypoint_count=int(len(xy)),
        cache=raw,
    )


def resolve_dji_image(incoming_wall: Path, name: str) -> Path:
    matches = list(incoming_wall.rglob(name))
    files = [p for p in matches if p.is_file()]
    if len(files) != 1:
        raise FileNotFoundError(f"expected one incoming image named {name}, found {len(files)}")
    return files[0]


def load_extracted_cache(cache: Path, *, image_id: int, name: str, image_path: Path) -> ExtractedImage:
    width, height, xy, desc = read_rve1(cache)
    return ExtractedImage(
        image_id=image_id,
        name=name,
        path=image_path,
        width=width,
        height=height,
        xy=xy,
        descriptors=desc,
        keypoint_count=int(len(xy)),
        cache=cache,
    )


def extract_all_reference_images(
    root: Path,
    incoming_wall: Path,
    observations,
    dest: Path,
) -> tuple[list[ExtractedImage], dict]:
    provenance = load_pinned_opencv(root)
    cli = Path(provenance["cli"])
    if not cli.is_file():
        raise OpenCVProvenanceError("pinned OpenCV CLI missing")
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[ExtractedImage] = []
    for obs in observations:
        cache = dest / f"{obs.image_id:04d}_{Path(obs.name).stem}.rve1"
        image_path = resolve_dji_image(incoming_wall, Path(obs.name).name)
        if not cache.is_file():
            extract_reference_image(cli, image_path, image_id=obs.image_id, name=obs.name, dest=cache)
        width, height, count = read_rve1_header(cache)
        item = ExtractedImage(
            image_id=obs.image_id,
            name=obs.name,
            path=image_path,
            width=width,
            height=height,
            xy=np.zeros((0, 2), dtype=np.float64),
            descriptors=np.zeros((0, DESCRIPTOR_DIM), dtype=np.float32),
            keypoint_count=count,
            cache=cache,
        )
        if item.width != obs.width or item.height != obs.height:
            raise RuntimeError(
                f"{obs.name} OpenCV size {item.width}x{item.height} != COLMAP {obs.width}x{obs.height}"
            )
        print(f"extracted {obs.name} keypoints={item.keypoint_count} size={item.width}x{item.height}", flush=True)
        extracted.append(item)
    summary = {
        "opencv": provenance,
        "grayscaleNote": GRAYSCALE_NOTE,
        "sift": {
            "nfeatures": SIFT_NFEATURES,
            "nOctaveLayers": SIFT_N_OCTAVE_LAYERS,
            "contrastThreshold": SIFT_CONTRAST_THRESHOLD,
            "edgeThreshold": SIFT_EDGE_THRESHOLD,
            "sigma": SIFT_SIGMA,
            "descriptorDim": DESCRIPTOR_DIM,
            "descriptorDtype": "float32",
        },
        "images": [
            {
                "imageId": item.image_id,
                "name": item.name,
                "width": item.width,
                "height": item.height,
                "opencvFeatures": item.keypoint_count,
            }
            for item in extracted
        ],
        "opencvFeaturesTotal": int(sum(item.keypoint_count for item in extracted)),
    }
    return extracted, summary
