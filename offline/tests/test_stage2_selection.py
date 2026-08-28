from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.metric_registration.frames import origin_compatible_with_mrk
from offline.metric_registration.height_datum import verify_height_datum
from offline.metric_registration.holdout import split_rule_description
from offline.metric_registration.pipeline import _judge
from offline.stage2_selection.select import select_stage2_inputs
from offline.testdata.ingestion.jpeg_exif import write_jpeg

WALL = "wall_test_stage2"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _dji(path: Path, seq: int, date: str = "20260823", time: str = "122200") -> Path:
    name = f"DJI_{date}{time}_{seq:04d}_V.JPG"
    dest = path / name
    write_jpeg(dest, make="DJI", model="M4E")
    return dest


def _mrk(path: Path, photo_ids: list[int], name: str = "DJI_20260823122200_0002_D.MRK") -> Path:
    lines = []
    for pid in photo_ids:
        lines.append(
            f"{pid}\t100.0\t[2433]\t0,N\t0,E\t0,V\t30.13000000,Lat\t118.01500000,Lon\t350.000,Ellh\t50,Q"
        )
    dest = path / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def _metadata(
    path: Path,
    *,
    srs: str = "EPSG:32650",
    origin: str = "597786.85842445458,3333597.1281958264,352.50399999973473",
) -> Path:
    dest = path / "metadata.xml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ModelMetadata version="1">\n'
        f"<SRS>{srs}</SRS>\n"
        f"<SRSOrigin>{origin}</SRSOrigin>\n"
        "</ModelMetadata>\n",
        encoding="utf-8",
    )
    return dest


def _ply(path: Path) -> Path:
    dest = path / "cloud.ply"
    dest.parent.mkdir(parents=True, exist_ok=True)
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(pts)}\n"
        "property float x\nproperty float y\nproperty float z\nend_header\n"
    ).encode("ascii")
    dest.write_bytes(header + pts.tobytes(order="C"))
    return dest


def _select(tmp: Path, wall_id: str = WALL) -> dict:
    return select_stage2_inputs(wall_id, tmp)


class Stage2SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_s2_"))
        self.wall = self.tmp / "incoming" / WALL
        self.wall.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _complete_unique(self) -> Path:
        cap = self.wall / "flight"
        for seq in (1, 2, 3):
            _dji(cap, seq)
        _mrk(cap, [1, 2, 3])
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply")
        return cap

    def test_unique_valid_capture_selection(self) -> None:
        self._complete_unique()
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(artifact["outputFrame"], "WallLocal")
        self.assertEqual(artifact["wallMetricMetersProvenance"], "NOT_CLAIMED")
        self.assertEqual(len(artifact["selectedCapture"]["memberRelativePaths"]), 3)
        self.assertTrue(artifact["selectedMRKSource"]["relativePath"].endswith(".MRK"))
        self.assertEqual(artifact["selectedSRS"], "EPSG:32650")
        self.assertEqual(len(artifact["selectedSRSOrigin"]), 3)
        self.assertFalse(artifact["selectionEvidence"]["nearestGpsAuthoritative"])
        self.assertTrue(artifact["selectionEvidence"]["colmapReadinessNotRequired"])
        self.assertTrue(artifact["selectionEvidence"]["sessionDji20260823NotRequired"])
        self.assertTrue(artifact["selectionEvidence"]["expectedImageCountNotRequired"])
        self.assertFalse(artifact["originCompatibilityIsProvenanceProof"])
        self.assertNotEqual(artifact["selectedCapture"]["memberCount"], 47)

    def test_zero_compatible_capture(self) -> None:
        write_jpeg(self.wall / "IMG_0001.JPG", make="Apple", model="iPhone")
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("ZERO_COMPATIBLE_PRIMARY_CAPTURE", artifact["selectionReasonCodes"])

    def test_multiple_valid_captures(self) -> None:
        for folder, date in (("A", "20260823"), ("B", "20260824")):
            cap = self.wall / folder
            for seq in (1, 2):
                _dji(cap, seq, date=date)
            _mrk(cap, [1, 2], name=f"DJI_{date}122200_0002_D.MRK")
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply")
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "HUMAN_REVIEW_REQUIRED")
        self.assertIn("MULTIPLE_SELECTABLE_CAPTURE_GROUPS", artifact["selectionReasonCodes"])

    def test_mrk_missing(self) -> None:
        cap = self.wall / "flight"
        _dji(cap, 1)
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply")
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("MRK_MISSING", artifact["selectionReasonCodes"])

    def test_mrk_same_parent_proven(self) -> None:
        self._complete_unique()
        artifact = _select(self.tmp)
        mrk = artifact["selectedMRKSource"]
        self.assertEqual(mrk["associationMethod"], "filename_sequence==MRK.photoId + same_parent_directory")
        self.assertTrue(mrk["frozenJiulongfengRuleAlsoHolds"])
        self.assertEqual(mrk["associationRule"], "GENERIC_MRK_ASSOCIATION_RULE")

    def test_mrk_non_same_parent_insufficient_evidence(self) -> None:
        cap = self.wall / "flight"
        for seq in (1, 2, 3):
            _dji(cap, seq)
        _mrk(self.wall / "other_rtk", [1, 2, 3])
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply")
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertIn("MRK_NON_SAME_PARENT_INSUFFICIENT_EVIDENCE", artifact["selectionReasonCodes"])
        self.assertIsNone(artifact["selectedMRKSource"])

    def test_does_not_guess_first_or_lexicographic_mrk(self) -> None:
        cap = self.wall / "flight"
        for seq in (1, 2):
            _dji(cap, seq)
        _mrk(self.wall / "aaa_first", [1, 2], name="aaa.MRK")
        _mrk(self.wall / "zzz_last", [1, 2], name="zzz.MRK")
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply")
        artifact = _select(self.tmp)
        self.assertIsNone(artifact["selectedMRKSource"])
        self.assertNotEqual(artifact["selectionStatus"], "AUTO_PASS")

    def test_does_not_use_nearest_gps_as_authority(self) -> None:
        cap = self.wall / "flight"
        _dji(cap, 1)
        far = self.wall / "far.MRK"
        near = self.wall / "other" / "near.MRK"
        _write(
            far,
            "1\t100.0\t[2433]\t0,N\t0,E\t0,V\t40.00000000,Lat\t120.00000000,Lon\t10.000,Ellh\t50,Q\n",
        )
        _write(
            near,
            "1\t100.0\t[2433]\t0,N\t0,E\t0,V\t30.13000000,Lat\t118.01500000,Lon\t350.000,Ellh\t50,Q\n",
        )
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply")
        artifact = _select(self.tmp)
        self.assertFalse(artifact["selectionEvidence"]["nearestGpsAuthoritative"])
        self.assertIsNone(artifact["selectedMRKSource"])
        json.dumps(artifact)

    def test_multiple_mrk_ambiguity(self) -> None:
        cap = self.wall / "flight"
        for seq in (1, 2):
            _dji(cap, seq)
        _mrk(cap, [1, 2], name="DJI_20260823122200_0001_D.MRK")
        _mrk(cap, [1, 2], name="DJI_20260823122200_0002_D.MRK")
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply")
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "HUMAN_REVIEW_REQUIRED")
        self.assertIn("MRK_AMBIGUOUS", artifact["selectionReasonCodes"])

    def test_metadata_missing(self) -> None:
        cap = self.wall / "flight"
        _dji(cap, 1)
        _mrk(cap, [1])
        _ply(self.wall / "export" / "terra_ply")
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("MODEL_SPATIAL_METADATA_MISSING", artifact["selectionReasonCodes"])

    def test_metadata_malformed(self) -> None:
        cap = self.wall / "flight"
        _dji(cap, 1)
        _mrk(cap, [1])
        _write(self.wall / "export" / "terra_ply" / "metadata.xml", "<ModelMetadata><SRS>EPSG:32650</SRS><SRSOrigin>nope</SRSOrigin></ModelMetadata>\n")
        _ply(self.wall / "export" / "terra_ply")
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("SRSORIGIN_MALFORMED", artifact["selectionReasonCodes"])

    def test_does_not_choose_first_metadata_xml(self) -> None:
        cap = self.wall / "flight"
        _dji(cap, 1)
        _mrk(cap, [1])
        _metadata(self.wall / "aaa" / "terra_ply")
        _metadata(self.wall / "zzz" / "terra_ply")
        _ply(self.wall / "export")
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertIn("MODEL_METADATA_ASSOCIATION_RULE_INSUFFICIENT", artifact["selectionReasonCodes"])
        self.assertIsNone(artifact["selectedModelSpatialMetadata"])

    def test_srs_not_epsg_32650(self) -> None:
        cap = self.wall / "flight"
        _dji(cap, 1)
        _mrk(cap, [1])
        _metadata(self.wall / "export" / "terra_ply", srs="EPSG:32651")
        _ply(self.wall / "export" / "terra_ply")
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertIn("SRS_NOT_EPSG_32650", artifact["selectionReasonCodes"])

    def test_origin_compatibility_is_sanity_not_provenance(self) -> None:
        origin = np.array([0.0, 0.0, 0.0])
        metrics = [np.array([10.0, 10.0, 1.0])]
        check = origin_compatible_with_mrk(origin, metrics)
        self.assertTrue(check["compatible"])
        self.assertEqual(check["semantics"], "SPATIAL_SANITY_CHECK")
        self.assertFalse(check["isCaptureModelProvenanceProof"])
        self.assertTrue(check["doesNotProveSameReconstruction"])

    def test_generic_height_does_not_require_legacy_20260812(self) -> None:
        height = verify_height_datum(self.wall, [1.0, 2.0, 3.0], require_legacy_proof=False)
        self.assertFalse(height["mixedDatumDetected"])
        self.assertFalse(height["legacyProofRequired"])
        self.assertFalse((self.wall / "dji_flight_raw_jiulongfeng").exists())

    def test_holdout_count_not_hard_coded(self) -> None:
        rule = split_rule_description(n_rows=20)
        self.assertEqual(rule["holdoutCount"], 5)
        self.assertEqual(rule["fitCount"], 15)
        self.assertNotIn("expectedHoldout", rule)
        self.assertNotIn("expectedFit", rule)

    def test_judge_does_not_require_47_on_generic_path(self) -> None:
        validation, gate, problems = _judge(
            proper=True,
            n_corr=3,
            conditioning="GOOD",
            fit_stats={"median": 0.1},
            hold_stats={"median": 0.2, "p90": 0.3},
            scale_spread=0.01,
            landmarks={"hasNan": False, "hasInf": False, "kilometerScaleExplosion": False},
            ply={"status": "ok", "median": 1.0},
            mixed_datum=False,
            origin_ok=True,
            extra_errors=[],
            expected_correspondences=None,
        )
        self.assertFalse(any("47" in p for p in problems))
        self.assertEqual(gate, "PASS")

    def test_ply_missing(self) -> None:
        cap = self.wall / "flight"
        _dji(cap, 1)
        _mrk(cap, [1])
        _metadata(self.wall / "export" / "terra_ply")
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("PLY_MISSING", artifact["selectionReasonCodes"])

    def test_ply_ambiguous_not_lexicographic(self) -> None:
        cap = self.wall / "flight"
        _dji(cap, 1)
        _mrk(cap, [1])
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "aaa")
        _ply(self.wall / "zzz")
        artifact = _select(self.tmp)
        self.assertEqual(artifact["selectionStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertIn("PLY_AMBIGUOUS_NO_APPROVED_RULE", artifact["selectionReasonCodes"])
        self.assertIsNone(artifact["selectedModelSource"])

    def test_no_wall_id_production_branch_in_selection_layer(self) -> None:
        text = (ROOT / "offline" / "stage2_selection" / "select.py").read_text(encoding="utf-8")
        self.assertNotIn("wall_jiulongfeng_01", text)
        self.assertNotIn("dji_20260823", text)


if __name__ == "__main__":
    unittest.main()
