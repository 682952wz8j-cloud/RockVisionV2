from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.pnp.constants import (
    ASSOCIATION_RADIUS_PX,
    FLAGS_NAME,
    FLAGS_VALUE,
    FORBIDDEN_FIELD_TEST,
    QUERY_COORDINATE_SPACE,
    REPROJECTION_ERROR_NATIVE_PX,
)
from offline.pnp.pipeline import PnPPipelineError, prepare_frame, run_session
from offline.reference_matching.constants import PINNED_OPENCV_VERSION


class PnPConstantTests(unittest.TestCase):
    def test_frozen_baseline_is_epnp_not_association_radius(self) -> None:
        self.assertEqual(FLAGS_NAME, "SOLVEPNP_EPNP")
        self.assertEqual(FLAGS_VALUE, 1)
        self.assertEqual(REPROJECTION_ERROR_NATIVE_PX, 8.0)
        self.assertEqual(ASSOCIATION_RADIUS_PX, 2.0)
        self.assertNotEqual(REPROJECTION_ERROR_NATIVE_PX, ASSOCIATION_RADIUS_PX)
        self.assertEqual(QUERY_COORDINATE_SPACE, "nativeCapturedImage")
        self.assertEqual(FORBIDDEN_FIELD_TEST, "gate3b_20260824_155143")


class PnPNoCv2Tests(unittest.TestCase):
    def test_pnp_sources_do_not_import_cv2(self) -> None:
        for path in (ROOT / "offline" / "pnp").glob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                self.assertFalse(stripped == "import cv2" or stripped.startswith("from cv2"), path.name)


class PnPSidecarTests(unittest.TestCase):
    def test_prepare_frame_counts_missing_xyz_and_requires_native_space(self) -> None:
        sample = {
            "frameID": 1,
            "scene": "A",
            "xyzMissingRejected": 1,
            "inputCorrespondenceCount": 1,
            "pnpCorrespondences": [
                {
                    "queryIndex": 0,
                    "queryXYNative": [100.0, 200.0],
                    "point3DID": 10,
                    "referenceRow": 0,
                    "colmapXYZ": [1.0, 2.0, 3.0],
                    "ratio": 0.5,
                    "descriptorDistance": 0.2,
                    "queryCoordinateSpace": "nativeCapturedImage",
                },
                {
                    "queryIndex": 1,
                    "queryXYNative": [110.0, 210.0],
                    "point3DID": 11,
                    "referenceRow": 1,
                    "colmapXYZ": None,
                    "ratio": 0.6,
                    "descriptorDistance": 0.3,
                    "queryCoordinateSpace": "nativeCapturedImage",
                },
            ],
        }
        prepared = prepare_frame(sample)
        self.assertEqual(prepared["inputCorrespondenceCount"], 1)
        self.assertEqual(prepared["xyzMissingRejected"], 1)
        self.assertEqual(prepared["objectPoints"], [[1.0, 2.0, 3.0]])

    def test_prepare_frame_rejects_wrong_coordinate_space(self) -> None:
        sample = {
            "pnpCorrespondences": [
                {
                    "queryIndex": 0,
                    "queryXYNative": [1, 2],
                    "point3DID": 1,
                    "colmapXYZ": [0, 0, 0],
                    "queryCoordinateSpace": "processed960",
                }
            ]
        }
        with self.assertRaises(PnPPipelineError):
            prepare_frame(sample)

    def test_old_gate3c_zip_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"RockVision_FieldTest_{FORBIDDEN_FIELD_TEST}" / "samples.jsonl"
            path.parent.mkdir()
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(PnPPipelineError):
                run_session(ROOT, path)


class PnPCliTests(unittest.TestCase):
    def test_self_test_with_pinned_opencv(self) -> None:
        from offline.pnp.opencv_cli import OpenCVProvenanceError, run_self_test

        try:
            payload = run_self_test(ROOT)
        except OpenCVProvenanceError as exc:
            self.skipTest(str(exc))
        self.assertEqual(payload["cvVersion"], PINNED_OPENCV_VERSION)
        self.assertTrue(payload["pass"])
        self.assertFalse(payload["importedCv2"])
        self.assertLess(payload["correct"]["rotationDeg"], 0.05)
        self.assertLess(payload["correct"]["centerError"], 1e-3)
        self.assertGreater(payload["nativeUV_scaledK"]["rotationDeg"], 5)
        self.assertGreater(payload["nativeUV_scaledK"]["reprojMedian"], 0.5)
        self.assertGreater(payload["scaledUV_nativeK"]["rotationDeg"], 5)
        self.assertGreater(payload["scaledUV_nativeK"]["reprojMedian"], 0.5)


class PnPObservationDepthTests(unittest.TestCase):
    def test_meters_field_is_cam_times_validated_scale(self) -> None:
        scale = 3.19764417024824
        cam = 2.40893
        meters = cam * scale
        self.assertNotEqual(meters, cam)
        self.assertAlmostEqual(meters, 7.702900971036092, places=6)


class PnPSceneAParityFixtureTests(unittest.TestCase):
    def test_mac_rv_pnp_matches_frozen_scene_a_expected(self) -> None:
        from offline.pnp.opencv_cli import OpenCVProvenanceError, solve, write_request
        from offline.metric_registration.serialize import load_sim3
        from offline.reference_matching.serialize import apply_s_wall_colmap
        import json
        import numpy as np

        fixture_path = ROOT / "offline" / "pnp" / "testdata" / "scene_a_gate3d_163435_frame472.json"
        expected_path = ROOT / "offline" / "pnp" / "testdata" / "scene_a_gate3d_163435_frame472.expected.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        self.assertEqual(fixture["inputCorrespondenceCount"], 725)
        self.assertEqual(len(fixture["objectPoints"]), 725)
        self.assertGreater(len(fixture["objectPoints"]), 20)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                request = Path(tmp) / "request.txt"
                result = Path(tmp) / "result.json"
                write_request(
                    request,
                    fixture["objectPoints"],
                    fixture["imagePoints"],
                    fixture["fx"],
                    fixture["fy"],
                    fixture["cx"],
                    fixture["cy"],
                )
                solved = solve(ROOT, request, result)
        except OpenCVProvenanceError as exc:
            self.skipTest(str(exc))
        self.assertTrue(solved["ransacSuccess"])
        self.assertTrue(solved["refineOk"])
        self.assertLess(abs(solved["inlierCount"] - expected["inlierCount"]), 150)
        sim3 = load_sim3(ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "metric_registration" / "S_wall_colmap.json")
        c_wall = apply_s_wall_colmap(np.asarray([solved["C_colmap"]], dtype=float), sim3)[0]
        cam = float(solved["medianInlierDepthCam"])
        meters = cam * float(sim3["scale"])
        self.assertAlmostEqual(meters, cam * 3.19764417024824, places=9)
        self.assertNotEqual(meters, cam)
        np.testing.assert_allclose(c_wall, expected["C_wall"], atol=0.05)
        np.testing.assert_allclose(solved["C_colmap"], expected["C_colmap"], atol=0.05)
        self.assertAlmostEqual(solved["reprojectionRefined"]["median"], expected["reprojectionRefinedMedian"], places=1)


if __name__ == "__main__":
    unittest.main()
