from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.colmap.layout import check_incoming_layout, is_new_dji_relative, normalize_wall_relative
from offline.colmap.manifest import select_source_images
from offline.colmap.metrics import (
    decide_gate_result,
    observations_from_reconstruction,
    sparse_from_reconstruction,
    split_pair_id,
    unpack_pair_table,
)
from offline.testdata.ingestion.jpeg_exif import write_jpeg


def _image(rel: str, session: str, role: str = "originalCameraImage", **extra) -> dict:
    name = Path(rel).name
    rec = {
        "relativePath": rel,
        "filename": name,
        "role": role,
        "captureSession": session,
        "sourceDevice": "DJI" if session.startswith("dji") or session.startswith("legacy") else "iPhone",
        "colmapSourceCandidate": session == "dji_20260823",
        "cameraMake": "DJI",
        "cameraModel": "M4E",
        "captureTimestamp": "2026:08:23 12:22:12",
        "dimensions": {"width": 5280, "height": 3956},
        "focalLength": "12.29",
        "focalLength35mm": "24",
    }
    rec.update(extra)
    return rec


def _assoc(rel: str, photo_id: int, status: str = "PROVEN") -> dict:
    return {
        "image": rel,
        "matchedMrk": status == "PROVEN",
        "mrkNearest": {"photoId": photo_id},
        "association": {"status": status, "statement": "test", "evidence": []},
    }


class ColmapGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_colmap_"))
        self.incoming = self.tmp / "incoming"
        self.wall = self.incoming / "wall_fixture"
        self.dji = self.wall / "DJI_202608231218_006_九龙峰"
        self.dji.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_normalize_strips_legacy_sibling_prefix(self) -> None:
        self.assertEqual(
            normalize_wall_relative("../DJI_202608231218_006_九龙峰/DJI_20260823122212_0001_V.JPG"),
            "DJI_202608231218_006_九龙峰/DJI_20260823122212_0001_V.JPG",
        )
        self.assertTrue(is_new_dji_relative("../DJI_202608231218_006_九龙峰/a.JPG"))
        self.assertFalse(is_new_dji_relative("0823 iphone拍摄/IMG_1506.HEIC"))
        self.assertFalse(is_new_dji_relative("dji_flight_raw_jiulongfeng/flight/DJI_20260811104240_0001_V.JPG"))

    def test_loose_incoming_root_is_a_stop(self) -> None:
        (self.incoming / "DJI_202608231218_006_九龙峰").mkdir(parents=True)
        errors = check_incoming_layout(self.tmp, "wall_fixture")
        self.assertTrue(any("loose capture" in item for item in errors))

    def test_source_set_keeps_only_new_dji_session(self) -> None:
        images = []
        assocs = []
        for idx in range(1, 49):
            if idx == 2:
                continue
            name = f"DJI_20260823122212_{idx:04d}_V.JPG"
            rel = f"../DJI_202608231218_006_九龙峰/{name}"
            write_jpeg(self.dji / name)
            images.append(_image(rel, "dji_20260823", captureTimestamp=f"2026:08:23 12:22:{idx:02d}"))
            assocs.append(_assoc(rel, idx))
        images.append(
            _image(
                "dji_flight_raw_jiulongfeng/flight/DJI_20260811104240_0001_V.JPG",
                "legacy_dji_20260811",
            )
        )
        images.append(
            _image(
                "../0823 iphone拍摄/IMG_1506.HEIC",
                "iphone_20260823",
                sourceDevice="iPhone 17 Pro",
            )
        )
        selected, errors = select_source_images({"files": images}, assocs, self.wall)
        self.assertEqual(errors, [])
        self.assertEqual(len(selected), 47)
        self.assertTrue(all(row["captureSession"] == "dji_20260823" for row in selected))
        self.assertTrue(all(row["mrkAssociationStatus"] == "PROVEN" for row in selected))
        names = {row["filename"] for row in selected}
        self.assertNotIn("DJI_20260811104240_0001_V.JPG", names)
        self.assertNotIn("IMG_1506.HEIC", names)
        self.assertEqual(selected[0]["relativePath"].split("/")[0], "DJI_202608231218_006_九龙峰")

    def test_source_set_rejects_wrong_count(self) -> None:
        write_jpeg(self.dji / "DJI_20260823122212_0001_V.JPG")
        images = [_image("../DJI_202608231218_006_九龙峰/DJI_20260823122212_0001_V.JPG", "dji_20260823")]
        assocs = [_assoc(images[0]["relativePath"], 1)]
        selected, errors = select_source_images({"files": images}, assocs, self.wall)
        self.assertEqual(len(selected), 1)
        self.assertTrue(any("expected 47" in item for item in errors))

    def test_metrics_from_text_reconstruction(self) -> None:
        try:
            import pycolmap
        except ImportError:
            self.skipTest("pycolmap required for reconstruction parsing test")
        model = self.tmp / "model"
        model.mkdir()
        (model / "cameras.txt").write_text(
            "# CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n1 SIMPLE_RADIAL 100 80 120 50 40 0\n",
            encoding="utf-8",
        )
        (model / "images.txt").write_text(
            "# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n"
            "1 1 0 0 0 0 0 0 1 a.jpg\n"
            "10.0 20.0 1\n"
            "2 1 0 0 0 1 0 0 1 b.jpg\n"
            "11.0 21.0 1\n\n",
            encoding="utf-8",
        )
        (model / "points3D.txt").write_text(
            "# POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)\n"
            "1 0 0 1 255 0 0 0.4 1 0 2 0\n",
            encoding="utf-8",
        )
        rec = pycolmap.Reconstruction()
        rec.read_text(str(model))
        obs = observations_from_reconstruction(rec)
        sparse = sparse_from_reconstruction(rec)
        self.assertEqual(obs["total"], 2)
        self.assertEqual(obs["imagesWithObservations"], 2)
        self.assertEqual(obs["stats"]["min"], 1)
        self.assertEqual(sparse["points3D"], 1)
        self.assertEqual(sparse["trackLength"]["median"], 2)
        self.assertAlmostEqual(sparse["reprojectionError"]["median"], 0.4)

    def test_gate_result_thresholds(self) -> None:
        self.assertEqual(
            decide_gate_result(
                source_count=47,
                registered=47,
                models=1,
                points3d=2000,
                observations=8000,
                median_track=3.0,
                median_reproj=0.8,
                incoming_unchanged=True,
                errors=[],
            ),
            "PASS",
        )
        self.assertEqual(
            decide_gate_result(
                source_count=47,
                registered=30,
                models=1,
                points3d=2000,
                observations=8000,
                median_track=3.0,
                median_reproj=0.8,
                incoming_unchanged=True,
                errors=[],
            ),
            "NEEDS REVIEW",
        )
        self.assertEqual(
            decide_gate_result(
                source_count=47,
                registered=0,
                models=0,
                points3d=0,
                observations=0,
                median_track=None,
                median_reproj=None,
                incoming_unchanged=True,
                errors=["no model"],
            ),
            "FAIL",
        )

    def test_pair_table_unpack(self) -> None:
        self.assertEqual(split_pair_id(2147483649), (1, 2))
        ids, values = unpack_pair_table(([2147483649], [[1, 2, 3]]))
        self.assertEqual(ids, [2147483649])
        self.assertEqual(values, [[1, 2, 3]])

    def test_colmap_readers_do_not_write_incoming(self) -> None:
        forbidden = (".unlink(", ".rmdir(", ".rename(", ".write_text(", ".write_bytes(", "os.remove", "shutil.move")
        readers = [
            ROOT / "offline/colmap/layout.py",
            ROOT / "offline/colmap/manifest.py",
            ROOT / "offline/colmap/metrics.py",
        ]
        for path in readers:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{path.name} contains {token}")


if __name__ == "__main__":
    unittest.main()
