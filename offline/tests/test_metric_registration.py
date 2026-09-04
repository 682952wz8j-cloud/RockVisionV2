from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.metric_registration.errors import error_stats
from offline.metric_registration.frames import (
    camera_center_from_world_to_camera,
    combine_conditioning,
    geodetic_to_projected_metric,
    pointset_geometry,
    to_wall_local,
)
from offline.metric_registration.holdout import split_fit_holdout
from offline.metric_registration.robust import ransac_umeyama
from offline.metric_registration.serialize import load_sim3, sim3_payload, write_json
from offline.metric_registration.umeyama import (
    Sim3Error,
    apply_sim3,
    invert_sim3,
    is_proper_rotation,
    matrix4x4_row_major,
    residuals,
    umeyama,
)


def _rotation_z(deg: float) -> np.ndarray:
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _cube() -> np.ndarray:
    return np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 1.0, 0.0],
            [1.0, 0.0, 1.0],
            [0.0, 1.0, 1.0],
            [1.0, 1.0, 1.0],
        ]
    )


class CameraCenterTests(unittest.TestCase):
    def test_identity_pose_center_is_neg_t(self) -> None:
        rotation = np.eye(3)
        translation = np.array([1.0, -2.0, 4.0])
        center = camera_center_from_world_to_camera(rotation, translation)
        np.testing.assert_allclose(center, -translation)
        self.assertFalse(np.allclose(center, translation))

    def test_rotated_pose_uses_minus_r_transpose_t(self) -> None:
        rotation = _rotation_z(30)
        translation = np.array([0.5, 1.5, -2.0])
        center = camera_center_from_world_to_camera(rotation, translation)
        np.testing.assert_allclose(center, -rotation.T @ translation)
        # World origin projected: R*0 + t = t, so camera sees origin at t; center != t.
        self.assertGreater(np.linalg.norm(center - translation), 0.5)


class GeodesyAndWallLocalTests(unittest.TestCase):
    def test_geodetic_to_utm_zone_50_known_ref_gps(self) -> None:
        metric = geodetic_to_projected_metric(30.12974461, 118.015181617, 352.504)
        self.assertAlmostEqual(metric[0], 597786.85842445458, places=3)
        self.assertAlmostEqual(metric[1], 3333597.1281958264, places=3)
        self.assertEqual(metric[2], 352.504)

    def test_wall_local_is_translation_only(self) -> None:
        origin = np.array([597786.858, 3333597.128, 352.504])
        metric = np.array([597800.0, 3333610.0, 340.0])
        local = to_wall_local(metric, origin)
        np.testing.assert_allclose(local, metric - origin)
        self.assertAlmostEqual(local[0], 13.142, places=3)


class UmeyamaSolverTests(unittest.TestCase):
    def test_identity(self) -> None:
        src = _cube()
        est = umeyama(src, src.copy())
        self.assertAlmostEqual(est["scale"], 1.0, places=9)
        np.testing.assert_allclose(est["rotation"], np.eye(3), atol=1e-9)
        np.testing.assert_allclose(est["translation"], np.zeros(3), atol=1e-9)

    def test_pure_translation(self) -> None:
        src = _cube()
        t = np.array([10.0, -3.0, 2.5])
        est = umeyama(src, src + t)
        self.assertAlmostEqual(est["scale"], 1.0, places=9)
        np.testing.assert_allclose(est["translation"], t, atol=1e-9)

    def test_known_scale(self) -> None:
        src = _cube()
        est = umeyama(src, 4.2 * src)
        self.assertAlmostEqual(est["scale"], 4.2, places=9)

    def test_known_rotation(self) -> None:
        src = _cube()
        rotation = _rotation_z(40)
        est = umeyama(src, (rotation @ src.T).T)
        np.testing.assert_allclose(est["rotation"], rotation, atol=1e-9)
        self.assertAlmostEqual(est["det"], 1.0, places=9)

    def test_combined_sim3(self) -> None:
        src = _cube()
        scale, rotation, t = 2.5, _rotation_z(-18), np.array([7.0, 1.0, -4.0])
        dst = apply_sim3(src, scale, rotation, t)
        est = umeyama(src, dst)
        self.assertAlmostEqual(est["scale"], scale, places=9)
        np.testing.assert_allclose(est["rotation"], rotation, atol=1e-9)
        np.testing.assert_allclose(est["translation"], t, atol=1e-9)
        self.assertTrue(is_proper_rotation(est["rotation"]))

    def test_noisy_correspondences(self) -> None:
        rng = np.random.default_rng(20260823)
        src = rng.normal(size=(40, 3))
        scale, rotation, t = 3.1, _rotation_z(12), np.array([1.0, 2.0, 3.0])
        dst = apply_sim3(src, scale, rotation, t) + rng.normal(scale=0.01, size=src.shape)
        est = umeyama(src, dst)
        self.assertAlmostEqual(est["scale"], scale, places=2)
        np.testing.assert_allclose(est["rotation"], rotation, atol=0.02)

    def test_reflection_rejected_or_proper(self) -> None:
        src = _cube()
        reflected = src.copy()
        reflected[:, 2] *= -1.0
        est = umeyama(src, reflected)
        self.assertGreater(est["det"], 0.0)
        self.assertTrue(is_proper_rotation(est["rotation"]))

    def test_insufficient_points(self) -> None:
        src = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        with self.assertRaises(Sim3Error):
            umeyama(src, src + 1.0)

    def test_near_collinear_rejected(self) -> None:
        src = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 1e-10, 0.0], [3.0, 0.0, 0.0]])
        with self.assertRaises(Sim3Error):
            umeyama(src, src * 2 + np.array([1.0, 0.0, 0.0]))


class Sim3ApplyAndDirectionTests(unittest.TestCase):
    def test_apply_matches_definition(self) -> None:
        src = _cube()
        scale, rotation, t = 1.7, _rotation_z(25), np.array([-2.0, 0.5, 8.0])
        pred = apply_sim3(src, scale, rotation, t)
        expected = scale * (rotation @ src.T).T + t
        np.testing.assert_allclose(pred, expected)

    def test_matrix4x4_row_major_column_vectors(self) -> None:
        src = _cube()
        scale, rotation, t = 2.0, _rotation_z(10), np.array([1.0, 2.0, 3.0])
        mat = np.asarray(matrix4x4_row_major(scale, rotation, t))
        homo = np.c_[src, np.ones(len(src))].T
        pred = (mat @ homo).T[:, :3]
        np.testing.assert_allclose(pred, apply_sim3(src, scale, rotation, t))

    def test_inverse_recovers_source(self) -> None:
        src = _cube()
        scale, rotation, t = 3.0, _rotation_z(-33), np.array([4.0, -1.0, 0.25])
        dst = apply_sim3(src, scale, rotation, t)
        inv_s, inv_r, inv_t = invert_sim3(scale, rotation, t)
        np.testing.assert_allclose(apply_sim3(dst, inv_s, inv_r, inv_t), src, atol=1e-9)

    def test_residuals_are_target_minus_predicted(self) -> None:
        src = _cube()
        dst = src + 1.0
        res = residuals(src, dst, 1.0, np.eye(3), np.zeros(3))
        np.testing.assert_allclose(res, np.ones_like(src))


class RobustAndHoldoutTests(unittest.TestCase):
    def test_ransac_recovers_with_outliers(self) -> None:
        rng = np.random.default_rng(7)
        src = rng.normal(size=(30, 3)) * 5
        scale, rotation, t = 1.8, _rotation_z(15), np.array([20.0, -4.0, 3.0])
        dst = apply_sim3(src, scale, rotation, t)
        dst[0] += np.array([50.0, 0.0, 0.0])
        dst[1] += np.array([0.0, -40.0, 0.0])
        used: list[int] = []
        est = ransac_umeyama(src, dst, threshold_m=0.25, seed=20260823, used_ids=used, min_inliers=10)
        self.assertAlmostEqual(est["scale"], scale, places=6)
        self.assertGreaterEqual(est["inlierCount"], 28)
        self.assertTrue(set(used).issubset(set(range(30))))

    def test_holdout_isolation(self) -> None:
        rows = [
            {"filename": f"img_{i:02d}.jpg", "mrkPhotoId": i, "colmapCenter": [float(i), 0.0, 0.1 * i], "wallLocal": [2.0 * i, 1.0, 0.2 * i]}
            for i in range(20)
        ]
        # Make a non-degenerate 3D set
        for i, row in enumerate(rows):
            row["colmapCenter"] = [float(i % 5), float(i // 5), float((i * 3) % 4)]
            row["wallLocal"] = [2 * x for x in row["colmapCenter"]]
        fit, hold = split_fit_holdout(rows, holdout_stride=4)
        self.assertEqual(len(hold), 5)
        self.assertEqual(len(fit), 15)
        hold_names = {r["filename"] for r in hold}
        used: list[int] = []
        src = np.asarray([r["colmapCenter"] for r in fit])
        dst = np.asarray([r["wallLocal"] for r in fit])
        ransac_umeyama(src, dst, threshold_m=0.5, used_ids=used, min_inliers=8)
        sampled = {fit[i]["filename"] for i in used}
        self.assertTrue(sampled.isdisjoint(hold_names))

    def test_error_stats_keys(self) -> None:
        res = np.array([[0.1, 0.0, 0.0], [0.0, 0.2, 0.0], [0.0, 0.0, 0.3]])
        stats = error_stats(res)
        self.assertIn("median", stats)
        self.assertIn("horizontal", stats)
        self.assertIn("vertical", stats)


class GeometryAndSerializeTests(unittest.TestCase):
    def test_degenerate_line_is_rejected_as_degenerate(self) -> None:
        line = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]])
        geom = pointset_geometry(line)
        self.assertEqual(geom["status"], "DEGENERATE")
        combined = combine_conditioning(geom, geom)
        self.assertEqual(combined["status"], "DEGENERATE")

    def test_serialize_roundtrip(self) -> None:
        payload = sim3_payload(
            scale=2.0,
            rotation=np.eye(3),
            translation=np.array([1.0, 2.0, 3.0]),
            origin={"origin": [1.0, 2.0, 3.0], "source": "test", "relativePath": "metadata.xml", "srs": "EPSG:32650"},
            fit_count=35,
            holdout_count=12,
            inlier_count=35,
            threshold_m=1.0,
            fit_metrics={"median": 0.1},
            holdout_metrics={"median": 0.2},
            solver_meta={"seed": 20260823, "iterations": 2000},
        )
        self.assertEqual(payload["sourceFrame"], "colmap_reconstruction_rhs_opencv_units")
        self.assertEqual(payload["targetFrame"], "wall_local_metres")
        self.assertIn("X_wall = s * R * X_colmap + t", payload["convention"])
        self.assertEqual(payload["matrix4x4"]["layout"], "row-major")
        tmp = Path(tempfile.mkdtemp()) / "S_wall_colmap.json"
        write_json(tmp, payload)
        loaded = load_sim3(tmp)
        self.assertEqual(loaded["scale"], 2.0)
        self.assertEqual(loaded["translationMeters"], [1.0, 2.0, 3.0])
        self.assertNotIn("wallBuildRunId", payload)

    def test_sim3_provenance_metadata_does_not_change_transform(self) -> None:
        rotation = np.eye(3)
        translation = np.array([1.0, 2.0, 3.0])
        base = sim3_payload(
            scale=2.0,
            rotation=rotation,
            translation=translation,
            origin={"origin": [0, 0, 0], "source": "test", "relativePath": "m.xml", "srs": "EPSG:32650"},
            fit_count=3,
            holdout_count=1,
            inlier_count=3,
            threshold_m=0.05,
            fit_metrics={"median": 0.1},
            holdout_metrics={"median": 0.2},
            solver_meta={"seed": 20260823, "iterations": 2000},
        )
        stamped = dict(base)
        stamped["wallId"] = "wall_fixture"
        stamped["wallBuildRunId"] = "wb_run"
        stamped["colmapModelFingerprint"] = "abc"
        stamped["modelFingerprint"] = "abc"
        self.assertEqual(stamped["scale"], base["scale"])
        self.assertEqual(stamped["rotationMatrix"], base["rotationMatrix"])
        self.assertEqual(stamped["translationMeters"], base["translationMeters"])
        self.assertEqual(stamped["matrix4x4"]["values"], base["matrix4x4"]["values"])
        tmp = Path(tempfile.mkdtemp()) / "S_wall_colmap.json"
        write_json(tmp, stamped)
        loaded = load_sim3(tmp)
        self.assertEqual(loaded["scale"], 2.0)
        self.assertEqual(loaded["wallBuildRunId"], "wb_run")

    def test_historical_sim3_without_provenance_remains_readable(self) -> None:
        path = ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "metric_registration" / "S_wall_colmap.json"
        if not path.is_file():
            self.skipTest("historical S_wall_colmap.json not present")
        loaded = load_sim3(path)
        self.assertEqual(loaded["status"], "VALIDATED")
        self.assertNotIn("wallBuildRunId", loaded)
        self.assertNotIn("colmapModelFingerprint", loaded)


if __name__ == "__main__":
    unittest.main()
