from __future__ import annotations

import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.reference_matching.associate import (
    REASON_ACCEPTED,
    REASON_NO_2PX,
    REASON_NOT_MUTUAL,
    REASON_UNIQUENESS,
    associate_xy,
    summarize_association,
)
from offline.reference_matching.compatibility import loo_compatibility, same_image_compatibility
from offline.reference_matching.constants import (
    CANDIDATE_K,
    DESCRIPTOR_DIM,
    MAX_PIXEL_DISTANCE,
    MIN_DISTINCT_POINT3D_FOR_RATIO,
    PINNED_OPENCV_COMMIT,
    PINNED_OPENCV_VERSION,
    RATIO_THRESHOLD,
)
from offline.reference_matching.extract import ExtractedImage
from offline.reference_matching.match import (
    REASON_ACCEPTED as MATCH_ACCEPTED,
    REASON_INSUFFICIENT,
    REASON_RATIO,
    knn_l2,
    match_queries,
    unique_point3d_dedup,
)
from offline.reference_matching.opencv_env import read_ios_pins, verify_ios_pins
from offline.reference_matching.serialize import (
    ArtifactError,
    apply_s_wall_colmap,
    freeze_artifact,
    read_rvs1,
    write_rvs1,
)


def _desc(*values: float) -> np.ndarray:
    row = np.zeros(DESCRIPTOR_DIM, dtype=np.float32)
    for i, value in enumerate(values):
        row[i] = value
    return row


class OpenCVProvenanceTests(unittest.TestCase):
    def test_ios_pin_files_match_frozen_source(self) -> None:
        pins = verify_ios_pins(ROOT)
        self.assertEqual(pins["commit"], PINNED_OPENCV_COMMIT)
        self.assertEqual(pins["version"], PINNED_OPENCV_VERSION)
        self.assertEqual(PINNED_OPENCV_COMMIT, "0654a42e19215ef25b1d367d822f3c630447e7c7")

    def test_mac_cli_is_414_when_built(self) -> None:
        from offline.reference_matching.opencv_env import OpenCVProvenanceError, load_pinned_opencv

        try:
            runtime = load_pinned_opencv(ROOT)
        except OpenCVProvenanceError as exc:
            self.skipTest(str(exc))
        self.assertEqual(runtime["cvVersion"], "4.14.0")
        self.assertEqual(runtime["commit"], PINNED_OPENCV_COMMIT)
        self.assertNotIn("site-packages/cv2", runtime.get("cli", ""))
        self.assertFalse(runtime.get("importedCv2"))
        self.assertNotIn("cv2File", runtime.get("provenance") or {})
        self.assertTrue((runtime.get("provenance") or {}).get("cliSha256"))
        self.assertTrue((runtime.get("provenance") or {}).get("runtimeExtraction"))
        pins = read_ios_pins(ROOT)
        self.assertEqual(pins["commit"], PINNED_OPENCV_COMMIT)
        self.assertNotEqual(pins["commit"], "4.14.0")


class AssociationTests(unittest.TestCase):
    def test_xy_mutual_and_2px_boundary(self) -> None:
        opencv = np.array([[0.0, 0.0], [8.0, 0.0]], dtype=np.float64)
        colmap = np.array([[2.0, 0.0], [8.0, 0.0]], dtype=np.float64)
        result = associate_xy(opencv, colmap, max_pixel_distance=2.0)
        self.assertEqual(MAX_PIXEL_DISTANCE, 2.0)
        self.assertEqual(result.reason[0], REASON_ACCEPTED)
        self.assertEqual(result.reason[1], REASON_ACCEPTED)
        self.assertAlmostEqual(float(result.nearest_distance[0]), 2.0)

        opencv_far = np.array([[0.0, 0.0], [0.2, 0.0]], dtype=np.float64)
        colmap_one = np.array([[0.15, 0.0]], dtype=np.float64)
        mutual = associate_xy(opencv_far, colmap_one)
        self.assertEqual(mutual.reason[0], REASON_NOT_MUTUAL)
        self.assertEqual(mutual.reason[1], REASON_ACCEPTED)

    def test_distance_just_over_2px_rejected(self) -> None:
        opencv = np.array([[0.0, 0.0]], dtype=np.float64)
        colmap = np.array([[2.0001, 0.0]], dtype=np.float64)
        result = associate_xy(opencv, colmap)
        self.assertEqual(result.reason[0], REASON_NO_2PX)

    def test_uniqueness_second_neighbor_within_2px(self) -> None:
        opencv = np.array([[0.0, 0.0]], dtype=np.float64)
        colmap = np.array([[0.4, 0.0], [1.2, 0.0]], dtype=np.float64)
        result = associate_xy(opencv, colmap)
        self.assertEqual(result.reason[0], REASON_UNIQUENESS)

    def test_reasons_are_exclusive_and_no3d_is_separate(self) -> None:
        opencv = np.array([[0.0, 0.0], [10.0, 0.0], [30.0, 0.0]], dtype=np.float64)
        colmap = np.array([[0.2, 0.0], [0.9, 0.0], [10.0, 0.0]], dtype=np.float64)
        result = associate_xy(opencv, colmap)
        summary = summarize_association(
            opencv_count=3,
            colmap_reconstructed=3,
            colmap_without_3d=17,
            result=result,
        )
        buckets = (
            summary["accepted"]
            + summary["mutualRejected"]
            + summary["uniquenessRejected"]
            + summary["twoPxRejected"]
        )
        self.assertEqual(buckets, 3)
        self.assertEqual(summary["no3DRejected"], 17)
        self.assertEqual(summary["accepted"] + summary["uniquenessRejected"] + summary["twoPxRejected"] + summary["mutualRejected"], 3)
        self.assertEqual(result.reason[0], REASON_UNIQUENESS)
        self.assertEqual(result.reason[1], REASON_ACCEPTED)
        self.assertEqual(result.reason[2], REASON_NO_2PX)

    def test_histogram_includes_rejected_nearest_distances(self) -> None:
        opencv = np.array([[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]], dtype=np.float64)
        colmap = np.array([[0.5, 0.0], [1.5, 0.0], [2.5, 0.0], [4.0, 0.0], [9.0, 0.0]], dtype=np.float64)
        # Use distinct opencv points so nearest distances map cleanly
        opencv = np.array([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0], [30.0, 0.0], [40.0, 0.0]], dtype=np.float64)
        colmap = np.array([[0.5, 0.0], [11.5, 0.0], [22.5, 0.0], [34.0, 0.0], [50.0, 0.0]], dtype=np.float64)
        result = associate_xy(opencv, colmap)
        hist = summarize_association(
            opencv_count=5,
            colmap_reconstructed=5,
            colmap_without_3d=0,
            result=result,
        )["nearestDistanceHistogram"]
        self.assertEqual(hist["0_1"], 1)
        self.assertEqual(hist["1_2"], 1)
        self.assertEqual(hist["2_3"], 1)
        self.assertEqual(hist["3_5"], 1)
        self.assertEqual(hist["gt_5"], 1)


class MatcherTests(unittest.TestCase):
    def test_duplicate_descriptors_same_point3d_ratio_uses_distinct_ids(self) -> None:
        reference = np.stack([_desc(1.0), _desc(1.01), _desc(0.0)])
        point3d = np.array([100, 100, 200], dtype=np.int64)
        query = _desc(1.0).reshape(1, -1)
        indices = np.array([[0, 1, 2] + [-1] * (CANDIDATE_K - 3)], dtype=np.int64)
        distances = np.array([[0.40, 0.41, 0.60] + [np.inf] * (CANDIDATE_K - 3)], dtype=np.float32)
        result = match_queries(query, reference, point3d, knn_indices=indices, knn_distances=distances)
        self.assertEqual(len(result.accepted_after_ratio), 1)
        self.assertEqual(result.accepted_after_ratio[0].point3d_id, 100)
        self.assertAlmostEqual(result.accepted_after_ratio[0].ratio, 0.40 / 0.60, places=6)
        self.assertLess(result.accepted_after_ratio[0].ratio, RATIO_THRESHOLD)
        raw_ratio = 0.40 / 0.41
        self.assertGreater(raw_ratio, RATIO_THRESHOLD)

    def test_only_one_distinct_point3d_is_insufficient(self) -> None:
        reference = np.stack([_desc(1.0), _desc(1.01)])
        point3d = np.array([100, 100], dtype=np.int64)
        query = _desc(1.0).reshape(1, -1)
        indices = np.array([[0, 1] + [-1] * (CANDIDATE_K - 2)], dtype=np.int64)
        distances = np.array([[0.1, 0.2] + [np.inf] * (CANDIDATE_K - 2)], dtype=np.float32)
        result = match_queries(query, reference, point3d, knn_indices=indices, knn_distances=distances)
        self.assertEqual(result.insufficient_distinct_point3d, 1)
        self.assertEqual(len(result.accepted_after_ratio), 0)
        self.assertEqual(result.records[0].reason, REASON_INSUFFICIENT)
        self.assertEqual(MIN_DISTINCT_POINT3D_FOR_RATIO, 2)

    def test_ratio_threshold_is_strict_less_than_0_8(self) -> None:
        reference = np.stack([_desc(1.0), _desc(0.0)])
        point3d = np.array([1, 2], dtype=np.int64)
        query = _desc(1.0).reshape(1, -1)
        indices = np.array([[0, 1] + [-1] * (CANDIDATE_K - 2)], dtype=np.int64)
        distances = np.array([[0.8, 1.0] + [np.inf] * (CANDIDATE_K - 2)], dtype=np.float32)
        result = match_queries(query, reference, point3d, knn_indices=indices, knn_distances=distances)
        self.assertEqual(RATIO_THRESHOLD, 0.8)
        self.assertEqual(result.records[0].reason, REASON_RATIO)
        self.assertEqual(len(result.accepted_after_ratio), 0)

    def test_duplicate_query_same_point3d_keeps_one(self) -> None:
        accepted = match_queries(
            np.stack([_desc(1.0), _desc(1.0)]),
            np.stack([_desc(1.0), _desc(0.0)]),
            np.array([9, 8], dtype=np.int64),
            knn_indices=np.array(
                [
                    [0, 1] + [-1] * (CANDIDATE_K - 2),
                    [0, 1] + [-1] * (CANDIDATE_K - 2),
                ],
                dtype=np.int64,
            ),
            knn_distances=np.array(
                [
                    [0.10, 0.50] + [np.inf] * (CANDIDATE_K - 2),
                    [0.20, 0.50] + [np.inf] * (CANDIDATE_K - 2),
                ],
                dtype=np.float32,
            ),
        )
        self.assertEqual(len(accepted.accepted_after_ratio), 2)
        self.assertEqual(len(accepted.accepted_unique_point3d), 1)
        self.assertEqual(accepted.accepted_unique_point3d[0].query_index, 0)
        self.assertEqual(accepted.duplicate_point3d_rejected, 1)

    def test_tie_break_uses_query_index(self) -> None:
        from offline.reference_matching.match import MatchRecord

        a = MatchRecord(query_index=5, reason=MATCH_ACCEPTED, point3d_id=7, distance=0.2, ratio=0.4)
        b = MatchRecord(query_index=1, reason=MATCH_ACCEPTED, point3d_id=7, distance=0.2, ratio=0.4)
        kept, rejected = unique_point3d_dedup([a, b])
        self.assertEqual(rejected, 1)
        self.assertEqual(kept[0].query_index, 1)

    def test_empty_query_and_reference(self) -> None:
        empty_q = np.zeros((0, DESCRIPTOR_DIM), dtype=np.float32)
        empty_r = np.zeros((0, DESCRIPTOR_DIM), dtype=np.float32)
        result = match_queries(empty_q, np.stack([_desc(1.0)]), np.array([1], dtype=np.int64))
        self.assertTrue(result.empty_query)
        self.assertEqual(len(result.records), 0)
        result = match_queries(np.stack([_desc(1.0)]), empty_r, np.zeros((0,), dtype=np.int64))
        self.assertTrue(result.empty_reference)
        self.assertEqual(result.records[0].reason, REASON_INSUFFICIENT)

    def test_non_finite_query_rejected(self) -> None:
        query = _desc(1.0).reshape(1, -1)
        query[0, 0] = np.nan
        result = match_queries(query, np.stack([_desc(1.0)]), np.array([1], dtype=np.int64))
        self.assertEqual(result.records[0].reason, "nonFiniteDescriptor")
        self.assertEqual(len(result.accepted_after_ratio), 0)

    def test_candidate_k_is_16(self) -> None:
        self.assertEqual(CANDIDATE_K, 16)
        reference = np.stack([_desc(float(i)) for i in range(20)])
        point3d = np.arange(20, dtype=np.int64) + 1
        query = _desc(0.0).reshape(1, -1)
        indices, distances = knn_l2(query, reference, k=CANDIDATE_K)
        self.assertEqual(indices.shape, (1, 16))
        result = match_queries(query, reference, point3d, knn_indices=indices, knn_distances=distances)
        self.assertEqual(result.records[0].raw_descriptor_candidates, 16)

    def test_bad_descriptor_dimension(self) -> None:
        with self.assertRaises(ValueError):
            match_queries(np.zeros((1, 64), dtype=np.float32), np.zeros((1, 64), dtype=np.float32), np.array([1]))


class SerializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_rvs1_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rvs1_roundtrip_float32_dim128(self) -> None:
        path = self.tmp / "descriptors.bin"
        matrix = np.stack([_desc(1.0, 2.0), _desc(3.0, 4.0)])
        write_rvs1(path, matrix)
        back = read_rvs1(path)
        np.testing.assert_array_equal(back, matrix)
        header = path.read_bytes()[:20]
        magic, version, dtype, dim, count = struct.unpack_from("<4sIIII", header, 0)
        self.assertEqual(magic, b"RVS1")
        self.assertEqual(version, 1)
        self.assertEqual(dtype, 1)
        self.assertEqual(dim, 128)
        self.assertEqual(count, 2)

    def test_malformed_magic_and_dim(self) -> None:
        bad = self.tmp / "bad.bin"
        bad.write_bytes(b"XXXX" + struct.pack("<IIII", 1, 1, 128, 0))
        with self.assertRaises(ArtifactError):
            read_rvs1(bad)
        with self.assertRaises(ArtifactError):
            write_rvs1(self.tmp / "d.bin", np.zeros((1, 64), dtype=np.float32))

    def test_non_finite_refused(self) -> None:
        matrix = np.stack([_desc(1.0)])
        matrix[0, 3] = np.inf
        with self.assertRaises(ArtifactError):
            write_rvs1(self.tmp / "inf.bin", matrix)

    def test_freeze_and_provenance_lookup(self) -> None:
        dest = self.tmp / "baseline_2px"
        desc = np.stack([_desc(1.0)])
        rows = [
            {
                "index": 0,
                "referenceImageID": 4,
                "referenceImageName": "DJI_TEST.JPG",
                "referenceKeypointX": 12.0,
                "referenceKeypointY": 34.0,
                "point3DID": 99,
                "colmapXYZ": [1.0, 2.0, 3.0],
                "wallLocalXYZ": [4.0, 5.0, 6.0],
            }
        ]
        freeze_artifact(
            dest,
            wall_id="wall_fixture",
            descriptors=desc,
            rows=rows,
            reference_images=[{"id": 4, "name": "DJI_TEST.JPG"}],
            association_report={"accepted": 1},
            database_stats={"sift": {"descriptorDim": 128}},
            opencv_provenance={"commit": PINNED_OPENCV_COMMIT},
            sim3={"status": "VALIDATED", "name": "S_wall_colmap", "convention": "X_wall = s * R * X_colmap + t"},
        )
        from offline.reference_matching.serialize import load_frozen

        frozen = load_frozen(dest)
        self.assertEqual(frozen["rows"][0]["point3DID"], 99)
        from offline.reference_matching.match import MatchRecord, provenance_for

        record = MatchRecord(query_index=0, reason=MATCH_ACCEPTED, point3d_id=99, reference_row=0, distance=0.1, ratio=0.2)
        prov = provenance_for(record, frozen["rows"])
        self.assertEqual(prov["referenceImageName"], "DJI_TEST.JPG")
        self.assertEqual(prov["referenceImageID"], 4)

    def test_existing_s_wall_colmap_transform(self) -> None:
        path = ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "metric_registration" / "S_wall_colmap.json"
        if not path.is_file():
            self.skipTest("S_wall_colmap.json not present")
        sim3 = json.loads(path.read_text())
        xyz = np.array([[0.0, 0.0, 0.0]], dtype=float)
        wall = apply_s_wall_colmap(xyz, sim3)
        np.testing.assert_allclose(wall[0], np.asarray(sim3["translationMeters"], dtype=float))
        self.assertEqual(sim3["status"], "VALIDATED")


class CompatibilityExclusionTests(unittest.TestCase):
    def test_loo_excludes_query_image_rows(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="rv_loo_"))
        try:
            query = _desc(1.0)
            other = _desc(0.0)
            desc = np.stack([query, other])
            dest = tmp / "baseline_2px"
            freeze_artifact(
                dest,
                wall_id="wall_fixture",
                descriptors=desc,
                rows=[
                    {
                        "index": 0,
                        "referenceImageID": 1,
                        "referenceImageName": "query.JPG",
                        "referenceKeypointX": 1.0,
                        "referenceKeypointY": 1.0,
                        "point3DID": 10,
                        "colmapXYZ": [0, 0, 0],
                        "wallLocalXYZ": [0, 0, 0],
                    },
                    {
                        "index": 1,
                        "referenceImageID": 2,
                        "referenceImageName": "other.JPG",
                        "referenceKeypointX": 2.0,
                        "referenceKeypointY": 2.0,
                        "point3DID": 11,
                        "colmapXYZ": [1, 1, 1],
                        "wallLocalXYZ": [1, 1, 1],
                    },
                ],
                reference_images=[{"id": 1, "name": "query.JPG"}, {"id": 2, "name": "other.JPG"}],
                association_report={},
                database_stats={"sift": {}},
                opencv_provenance={},
                sim3={"status": "VALIDATED", "name": "S_wall_colmap", "convention": "x"},
            )
            from offline.reference_matching.serialize import load_frozen

            frozen = load_frozen(dest)
            extracted = ExtractedImage(
                image_id=1,
                name="query.JPG",
                path=tmp / "query.JPG",
                width=10,
                height=10,
                xy=np.array([[1.0, 1.0]]),
                descriptors=np.stack([query, _desc(0.2)]),
                keypoint_count=2,
            )
            same = same_image_compatibility(None, frozen, extracted, "test")
            loo = loo_compatibility(None, frozen, extracted, "test")
            self.assertEqual(same["queryImageRowsExcluded"], 0)
            self.assertEqual(loo["queryImageRowsExcluded"], 1)
            self.assertGreater(loo["queryImageRowsExcluded"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
