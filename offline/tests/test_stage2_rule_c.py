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

from offline.qualification.rtk import parse_mrk
from offline.stage2_selection.ellipsoid import evaluate_rule_c
from offline.stage2_selection.select import select_stage2_inputs
from offline.testdata.ingestion.jpeg_exif import write_jpeg

WALL = "wall_test_rule_c"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _dji(
    folder: Path,
    seq: int,
    *,
    model: str = "M4E",
    xmp: dict[str, str] | None = None,
    gps_map_datum: str | None = None,
) -> Path:
    dest = folder / f"DJI_20260823122200_{seq:04d}_V.JPG"
    write_jpeg(dest, make="DJI", model=model, xmp=xmp, gps_map_datum=gps_map_datum)
    return dest


def _mrk(folder: Path, photo_ids: list[int] | None = None) -> Path:
    ids = photo_ids or [1]
    lines = [
        f"{pid}\t100.0\t[2433]\t0,N\t0,E\t0,V\t30.13000000,Lat\t118.01500000,Lon\t350.000,Ellh\t50,Q"
        for pid in ids
    ]
    dest = folder / "DJI_20260823122200_0002_D.MRK"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def _ply(folder: Path) -> Path:
    dest = folder / "cloud.ply"
    dest.parent.mkdir(parents=True, exist_ok=True)
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(pts)}\n"
        "property float x\nproperty float y\nproperty float z\nend_header\n"
    ).encode("ascii")
    dest.write_bytes(header + pts.tobytes(order="C"))
    return dest


def _metadata(folder: Path, srs: str = "EPSG:32650") -> Path:
    dest = folder / "metadata.xml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<ModelMetadata version=\"1\">\n"
        f"<SRS>{srs}</SRS>\n"
        "<SRSOrigin>100.0,200.0,10.0</SRSOrigin>\n"
        "</ModelMetadata>\n",
        encoding="utf-8",
    )
    return dest


def _terra_default(export: Path, *, vertical: str = "Default", sdk_override: str = "") -> None:
    _write(
        export / "report" / "model_report.json",
        json.dumps(
            {
                "output coordinate": "WGS 84 / UTM zone 50N",
                "output vertical coordinate": vertical,
            }
        ),
    )
    _write(
        export / "SDK_Log.txt",
        '[2026-08-29:17.22.38.360][I]Output geo descriptor: '
        f'{{"cs_type":"GEO_CS","geo_cs":"EPSG:32650","geo_cs_wkt":"","override_vertical_cs":"{sdk_override}"}}\n',
    )


def _eval(wall: Path, *, model: str = "M4E", extra_xmp: dict[str, str] | None = None) -> dict:
    cap = wall / "flight"
    jpg = _dji(cap, 1, model=model, xmp=extra_xmp)
    mrk = _mrk(cap, [1])
    export = wall / "export"
    _metadata(export / "terra_ply")
    _ply(export / "terra_ply")
    _terra_default(export)
    parsed = parse_mrk(mrk.read_text(encoding="utf-8"))
    return evaluate_rule_c(
        wall,
        capture_relative_paths=[jpg.relative_to(wall).as_posix()],
        camera_models=[model],
        mrk_relative_path=mrk.relative_to(wall).as_posix(),
        mrk_records=parsed["records"],
        terra_export_root_relative="export",
    )


class RuleCReferenceEllipsoidTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_rule_c_"))
        self.wall = self.tmp / "incoming" / WALL
        self.wall.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_matrice4_default_wgs84_by_approved_spec(self) -> None:
        result = _eval(self.wall)
        self.assertEqual(result["captureFamily"], "DJI_MATRICE_4_SERIES")
        self.assertEqual(result["referenceEllipsoid"], "WGS84")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC")
        self.assertTrue(result["specDefaultInvoked"])
        self.assertNotEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_WGS84")
        self.assertEqual(result["terminalStatus"], "AUTO_PASS")
        self.assertEqual(result["rtkSource"], "UNKNOWN")
        self.assertEqual(result["networkRtk"]["fieldsInspected"]["NTRIPHost"]["presence"], "FIELD_NOT_PRESENT")

    def test_b_network_rtk_blocks_default(self) -> None:
        result = _eval(self.wall, extra_xmp={"NTRIPHost": "203.0.113.10"})
        self.assertEqual(result["rtkSource"], "NETWORK_RTK")
        self.assertEqual(result["referenceEllipsoid"], "UNKNOWN")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "UNKNOWN")
        self.assertFalse(result["specDefaultInvoked"])
        self.assertEqual(result["terminalStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertEqual(result["reasonCode"], "RULE_C_NETWORK_RTK_ELLIPSOID_UNKNOWN")

    def test_c_explicit_cgcs2000(self) -> None:
        result = _eval(self.wall, extra_xmp={"RtkCoordinateSystem": "CGCS2000"})
        self.assertEqual(result["referenceEllipsoid"], "CGCS2000")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_NON_WGS84")
        self.assertEqual(result["datumCompatibilityStatus"], "INSUFFICIENT_STAGE2_CRS_CAPABILITY")
        self.assertFalse(result["specDefaultInvoked"])
        self.assertEqual(result["terminalStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertIn("RULE_C_INSUFFICIENT_STAGE2_CRS_CAPABILITY", result["reasonCodes"])

    def test_d_explicit_wgs84_is_proven(self) -> None:
        result = _eval(self.wall, extra_xmp={"RtkCoordinateSystem": "WGS84"})
        self.assertEqual(result["referenceEllipsoid"], "WGS84")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_WGS84")
        self.assertFalse(result["specDefaultInvoked"])

    def test_e_unknown_family_does_not_invoke_default(self) -> None:
        result = _eval(self.wall, model="FC6540")
        self.assertEqual(result["captureFamily"], "UNKNOWN")
        self.assertEqual(result["referenceEllipsoid"], "UNKNOWN")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "UNKNOWN")
        self.assertFalse(result["specDefaultInvoked"])
        self.assertEqual(result["terminalStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")

    def test_f_epsg32650_does_not_prove_capture_ellipsoid(self) -> None:
        cap = self.wall / "flight"
        jpg = _dji(cap, 1, model="FC6540")
        export = self.wall / "export"
        _metadata(export / "terra_ply", srs="EPSG:32650")
        _ply(export / "terra_ply")
        result = evaluate_rule_c(
            self.wall,
            capture_relative_paths=[jpg.relative_to(self.wall).as_posix()],
            camera_models=["FC6540"],
            terra_export_root_relative="export",
        )
        self.assertNotEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_WGS84")
        self.assertNotEqual(result["referenceEllipsoidProvenanceStatus"], "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC")
        self.assertEqual(result["referenceEllipsoid"], "UNKNOWN")
        self.assertTrue(result["defaultBranchGuards"]["epsg32650NotUsedAsProof"])

    def test_g_gps_map_datum_is_not_proven_wgs84(self) -> None:
        cap = self.wall / "flight"
        jpg = _dji(cap, 1, model="FC6540", gps_map_datum="WGS-84")
        result = evaluate_rule_c(
            self.wall,
            capture_relative_paths=[jpg.relative_to(self.wall).as_posix()],
            camera_models=["FC6540"],
        )
        self.assertTrue(result["gpsMapDatumEvidence"])
        self.assertEqual(result["gpsMapDatumEvidence"][0]["rawValue"], "WGS-84")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "UNKNOWN")
        self.assertNotEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_WGS84")

    def test_h_network_rtk_plus_explicit_wgs84_is_proven(self) -> None:
        result = _eval(
            self.wall,
            extra_xmp={"NTRIPHost": "203.0.113.10", "RtkCoordinateSystem": "WGS84"},
        )
        self.assertEqual(result["rtkSource"], "NETWORK_RTK")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_WGS84")
        self.assertEqual(result["referenceEllipsoid"], "WGS84")
        self.assertFalse(result["specDefaultInvoked"])
        self.assertEqual(result["terminalStatus"], "AUTO_PASS")

    def test_i_conflicting_explicit_evidence(self) -> None:
        result = _eval(
            self.wall,
            extra_xmp={"RtkCoordinateSystem": "WGS84", "Datum": "CGCS2000"},
        )
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "CONFLICTING_EVIDENCE")
        self.assertFalse(result["specDefaultInvoked"])
        self.assertEqual(result["terminalStatus"], "HUMAN_REVIEW_REQUIRED")

    def test_j_numeric_identity_is_not_ellipsoid_proof(self) -> None:
        result = evaluate_rule_c(self.wall)
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "UNKNOWN")
        self.assertTrue(result["defaultBranchGuards"]["numericalSanityNotUsedAsProof"])
        self.assertFalse(result["specDefaultInvoked"])

    def test_rtk_diff_age_is_not_network_rtk(self) -> None:
        result = _eval(self.wall, extra_xmp={"RtkDiffAge": "2.00000", "RtkFlag": "50"})
        self.assertEqual(result["rtkSource"], "UNKNOWN")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC")
        self.assertTrue(result["defaultBranchGuards"]["rtkDiffAgeNotUsedAsSource"])

    def test_selection_artifact_records_rule_c_without_changing_capture_pass(self) -> None:
        cap = self.wall / "flight"
        _dji(cap, 1)
        _mrk(cap, [1])
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply")
        artifact = select_stage2_inputs(WALL, self.tmp)
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(artifact["heightVerticalDatumProvenance"], "SEPARATE_DEVELOPMENT_GATE")
        prov = artifact["gnssReferenceEllipsoidProvenance"]
        self.assertEqual(prov["policy"], "RULE_C_SPEC_GOVERNED_DEFAULT")
        self.assertEqual(prov["captureFamily"], "DJI_MATRICE_4_SERIES")
        self.assertEqual(prov["referenceEllipsoidProvenanceStatus"], "UNKNOWN")
        self.assertFalse(prov["specDefaultInvoked"])
        self.assertTrue(artifact["selectionEvidence"]["gpsMapDatumIsNotProvenWgs84"])

    def test_empty_ntrip_does_not_count_as_network_rtk(self) -> None:
        result = _eval(self.wall, extra_xmp={"NTRIPHost": "", "NTRIPPort": "", "NTRIPMountPoint": ""})
        self.assertEqual(result["networkRtk"]["fieldsInspected"]["NTRIPHost"]["presence"], "FIELD_PRESENT_EMPTY")
        self.assertFalse(result["networkRtk"]["detected"])
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC")


if __name__ == "__main__":
    unittest.main()
