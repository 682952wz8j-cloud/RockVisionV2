from __future__ import annotations

import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.ingestion.hashing import sha256_file
from offline.stage2_selection.ply_product import (
    discover_ply_candidates,
    select_formal_terra_ply_product,
)
from offline.stage2_selection.select import select_stage2_inputs
from offline.testdata.ingestion.jpeg_exif import write_jpeg

WALL = "wall_test_ply_product"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _dji(path: Path, seq: int) -> Path:
    dest = path / f"DJI_20260823122200_{seq:04d}_V.JPG"
    write_jpeg(dest, make="DJI", model="M4E")
    return dest


def _mrk(path: Path, photo_ids: list[int]) -> Path:
    lines = [
        f"{pid}\t100.0\t[2433]\t0,N\t0,E\t0,V\t30.13000000,Lat\t118.01500000,Lon\t350.000,Ellh\t50,Q"
        for pid in photo_ids
    ]
    dest = path / "DJI_20260823122200_0002_D.MRK"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def _metadata(path: Path) -> Path:
    dest = path / "metadata.xml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<ModelMetadata version=\"1\">\n"
        "<SRS>EPSG:32650</SRS>\n"
        "<SRSOrigin>100.0,200.0,10.0</SRSOrigin>\n"
        "</ModelMetadata>\n",
        encoding="utf-8",
    )
    return dest


def _ply(path: Path, name: str = "cloud.ply") -> Path:
    dest = path / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(pts)}\n"
        "property float x\nproperty float y\nproperty float z\nend_header\n"
    ).encode("ascii")
    dest.write_bytes(header + pts.tobytes(order="C"))
    return dest


def _model_report(export: Path, *, generate_ply: bool = False, generate_point_ply: bool = False) -> Path:
    dest = export / "report" / "model_report.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps({"generate ply": generate_ply, "generate point ply": generate_point_ply}) + "\n",
        encoding="utf-8",
    )
    return dest


def _capture(wall: Path) -> None:
    cap = wall / "flight"
    _dji(cap, 1)
    _mrk(cap, [1])


class TerraPlyProductTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_ply_prod_"))
        self.wall = self.tmp / "incoming" / WALL
        self.wall.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _select(self, **kwargs):
        return select_stage2_inputs(WALL, self.tmp, **kwargs)

    def test_t1_one_valid_formal_terra_ply(self) -> None:
        _capture(self.wall)
        export = self.wall / "export"
        _metadata(export / "terra_point_ply")
        ply = _ply(export / "terra_point_ply", name="cloudR.ply")
        _model_report(export, generate_point_ply=True)
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        product = artifact["terraPlyProduct"]
        self.assertTrue(product["plyCandidateFound"])
        self.assertTrue(product["terraProductIdentified"])
        self.assertTrue(product["terraProductUnambiguous"])
        self.assertTrue(product["terraProductSelected"])
        self.assertTrue(product["terraProductProvenanceRecorded"])
        self.assertEqual(product["selected"]["relativePath"], "export/terra_point_ply/cloudR.ply")
        self.assertEqual(product["selected"]["sha256"], sha256_file(ply))
        self.assertEqual(artifact["selectedModelSource"]["relativePath"], "export/terra_point_ply/cloudR.ply")

    def test_t2_formal_plus_unrelated_and_temp(self) -> None:
        _capture(self.wall)
        export = self.wall / "export"
        _metadata(export / "terra_point_ply")
        _ply(export / "terra_point_ply", name="cloudR.ply")
        _ply(export / ".temp" / "Reconstruction3d", name="cloud_dense.ply")
        _ply(self.wall / "scratch", name="other.ply")
        _model_report(export, generate_point_ply=True)
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(
            artifact["selectedModelSource"]["relativePath"],
            "export/terra_point_ply/cloudR.ply",
        )
        reasons = {item["relativePath"]: item.get("rejectedReason") for item in artifact["terraPlyProduct"]["candidates"]}
        self.assertEqual(reasons["export/.temp/Reconstruction3d/cloud_dense.ply"], "NON_DELIVERABLE_INTERMEDIATE")
        self.assertEqual(reasons["scratch/other.ply"], "NOT_DECLARED_FORMAL_TERRA_PLY_PRODUCT")
        self.assertIsNone(reasons["export/terra_point_ply/cloudR.ply"])

    def test_t3_two_equally_valid_formal_products_fail_closed(self) -> None:
        _capture(self.wall)
        export = self.wall / "export"
        _metadata(export / "terra_ply")
        _metadata(export / "terra_point_ply")
        _ply(export / "terra_ply", name="mesh.ply")
        _ply(export / "terra_point_ply", name="cloud.ply")
        _model_report(export, generate_ply=True, generate_point_ply=True)
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("TERRA_PLY_PRODUCT_AMBIGUOUS", artifact["selectionReasonCodes"])
        self.assertIsNone(artifact["selectedModelSource"])
        self.assertFalse(artifact["terraPlyProduct"]["terraProductUnambiguous"])
        self.assertFalse(artifact["terraPlyProduct"]["terraProductSelected"])

    def test_t4_ply_exists_but_not_formal_fail_closed(self) -> None:
        _capture(self.wall)
        export = self.wall / "export"
        _metadata(export / "terra_obj")
        (export / "terra_obj").mkdir(parents=True, exist_ok=True)
        _ply(export / ".temp", name="cloud_dense.ply")
        _model_report(export, generate_ply=False, generate_point_ply=False)
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("TERRA_PLY_PRODUCT_NOT_PROVEN", artifact["selectionReasonCodes"])
        self.assertTrue(artifact["terraPlyProduct"]["plyCandidateFound"])
        self.assertFalse(artifact["terraPlyProduct"]["terraProductIdentified"])
        self.assertIsNone(artifact["selectedModelSource"])

    def test_t5_no_ply_keeps_missing_behavior(self) -> None:
        _capture(self.wall)
        export = self.wall / "export"
        _metadata(export / "terra_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertIn("GEOMETRY_CROSSCHECK_NOT_AVAILABLE", artifact["selectionReasonCodes"])
        self.assertFalse(artifact["terraPlyProduct"]["plyCandidateFound"])

    def test_t6_candidate_order_permutation_is_deterministic(self) -> None:
        export = self.wall / "export"
        _ply(export / "terra_point_ply", name="cloudR.ply")
        _ply(export / ".temp", name="aaa.ply")
        _ply(export / ".temp", name="zzz.ply")
        _model_report(export, generate_point_ply=True)
        base = discover_ply_candidates(self.wall)
        results = []
        for _ in range(8):
            shuffled = list(base)
            random.shuffle(shuffled)
            payload = select_formal_terra_ply_product(self.wall, candidates=shuffled)
            results.append(
                (
                    payload["status"],
                    payload["reasonCode"],
                    (payload.get("selected") or {}).get("relativePath"),
                    [item["relativePath"] for item in payload["candidates"]],
                )
            )
        self.assertEqual(len({item[:3] for item in results}), 1)
        self.assertEqual(results[0][2], "export/terra_point_ply/cloudR.ply")
        self.assertEqual(results[0][3], sorted(results[0][3]))

    def test_t7_provenance_completeness(self) -> None:
        _capture(self.wall)
        export = self.wall / "export"
        _metadata(export / "terra_point_ply")
        ply = _ply(export / "terra_point_ply", name="cloudR.ply")
        _ply(export / ".temp", name="cloud_dense.ply")
        _model_report(export, generate_point_ply=True)
        artifact = self._select()
        product = artifact["terraPlyProduct"]
        selected = product["selected"]
        self.assertEqual(selected["sha256"], sha256_file(ply))
        self.assertEqual(selected["relativePath"], "export/terra_point_ply/cloudR.ply")
        self.assertEqual(selected["fileSize"], ply.stat().st_size)
        self.assertGreaterEqual(product["plyCandidateCount"], 2)
        self.assertTrue(any(item["relativePath"].endswith("cloud_dense.ply") for item in product["candidates"]))
        self.assertIn("selectionRule", selected)
        rejected = [item for item in product["candidates"] if item["relativePath"].endswith("cloud_dense.ply")][0]
        self.assertEqual(rejected["rejectedReason"], "NON_DELIVERABLE_INTERMEDIATE")
        self.assertTrue(rejected["selected"] is False)

    def test_t8_frozen_run_ignores_later_incoming_ply(self) -> None:
        export = self.wall / "export"
        first = _ply(export / "terra_point_ply", name="cloudR.ply")
        _model_report(export, generate_point_ply=True)
        frozen = select_formal_terra_ply_product(self.wall)
        self.assertEqual(frozen["selected"]["relativePath"], "export/terra_point_ply/cloudR.ply")
        self.assertEqual(frozen["selected"]["sha256"], sha256_file(first))
        _ply(export / "terra_point_ply", name="another.ply")
        live = select_formal_terra_ply_product(self.wall)
        self.assertEqual(live["status"], "AUTO_FAIL")
        self.assertEqual(live["reasonCode"], "TERRA_PLY_PRODUCT_AMBIGUOUS")
        replay = select_formal_terra_ply_product(self.wall, frozen=frozen)
        self.assertTrue(replay["frozen"])
        self.assertEqual(replay["selected"]["relativePath"], "export/terra_point_ply/cloudR.ply")
        self.assertEqual(replay["selected"]["sha256"], sha256_file(first))
        self.assertEqual(replay["status"], "AUTO_PASS")

    def test_model_report_selects_declared_token_when_both_dirs_exist(self) -> None:
        _capture(self.wall)
        export = self.wall / "export"
        _metadata(export / "terra_ply")
        _metadata(export / "terra_point_ply")
        _ply(export / "terra_ply", name="mesh.ply")
        _ply(export / "terra_point_ply", name="cloud.ply")
        _model_report(export, generate_point_ply=True, generate_ply=False)
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(artifact["selectedCrosscheckProduct"]["productToken"], "terra_point_ply")
        self.assertEqual(artifact["selectedModelSource"]["relativePath"], "export/terra_point_ply/cloud.ply")


if __name__ == "__main__":
    unittest.main()
