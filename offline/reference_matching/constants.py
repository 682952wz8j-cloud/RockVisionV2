"""Frozen Gate 3C constants. Names, not magic numbers."""

from __future__ import annotations

PINNED_OPENCV_COMMIT = "0654a42e19215ef25b1d367d822f3c630447e7c7"
PINNED_OPENCV_TAG = "4.14.0"
PINNED_OPENCV_VERSION = "4.14.0"

SIFT_NFEATURES = 0
SIFT_N_OCTAVE_LAYERS = 3
SIFT_CONTRAST_THRESHOLD = 0.04
SIFT_EDGE_THRESHOLD = 10.0
SIFT_SIGMA = 1.6
DESCRIPTOR_DIM = 128
DESCRIPTOR_DTYPE = "float32"

MAX_PIXEL_DISTANCE = 2.0
ASSOCIATION_RADIUS_NAME = "baseline_2px"

CANDIDATE_K = 16
CANDIDATE_K_NAME = "candidateK"
MIN_DISTINCT_POINT3D_FOR_RATIO = 2
RATIO_THRESHOLD = 0.8

RVS1_MAGIC = b"RVS1"
RVS1_VERSION = 1
RVS1_DTYPE_FLOAT32 = 1

ARTIFACT_SCHEMA = "reference_matching.baseline_2px.1"
LANDMARKS_SCHEMA = 1

GRAYSCALE_NOTE = (
    "Reference: DJI JPEG -> OpenCV imread BGR -> cvtColor COLOR_BGR2GRAY -> SIFT. "
    "Runtime: ARFrame Y plane -> resize 960x720 -> SIFT. "
    "Sources differ; Gate 3C records this and does not retune preprocessing."
)
