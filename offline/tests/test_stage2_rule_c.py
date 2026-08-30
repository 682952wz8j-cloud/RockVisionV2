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
from offline.stage2_selection import ellipsoid as ellipsoid_mod
from offline.stage2_selection.ellipsoid import (
    APPROVED_CAPTURE_FAMILY_FIELDS,
    APPROVED_EXPLICIT_REFERENCE_SYSTEM_FIELDS,
    APPROVED_MATRICE_4_DRONE_MODELS,
    APPROVED_MATRICE_4_EXIF_MODELS,
    APPROVED_MATRICE_4_PRODUCT_NAMES,
    APPROVED_NETWORK_RTK_OVERRIDE_FIELDS,
    EVIDENCE_AUTHORITATIVE_ELLIPSOID,
    evaluate_rule_c,
    evaluate_rule_c_session,
    identify_capture_family,
)
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


def _structured(*systems: str) -> list[dict]:
    return [
        {
            "referenceSystem": name,
            "evidenceClass": EVIDENCE_AUTHORITATIVE_ELLIPSOID,
            "source": "synthetic-test-fixture",
        }
        for name in systems
    ]


def _eval(
    wall: Path,
    *,
    model: str = "M4E",
    extra_xmp: dict[str, str] | None = None,
    explicit_reference_evidence: list[dict] | None = None,
) -> dict:
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
        explicit_reference_evidence=explicit_reference_evidence or [],
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
        result = _eval(self.wall, explicit_reference_evidence=_structured("CGCS2000"))
        self.assertEqual(result["referenceEllipsoid"], "CGCS2000")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_NON_WGS84")
        self.assertEqual(result["datumCompatibilityStatus"], "INSUFFICIENT_STAGE2_CRS_CAPABILITY")
        self.assertFalse(result["specDefaultInvoked"])
        self.assertEqual(result["terminalStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertIn("RULE_C_INSUFFICIENT_STAGE2_CRS_CAPABILITY", result["reasonCodes"])

    def test_d_explicit_wgs84_is_proven(self) -> None:
        result = _eval(self.wall, explicit_reference_evidence=_structured("WGS84"))
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
            extra_xmp={"NTRIPHost": "203.0.113.10"},
            explicit_reference_evidence=_structured("WGS84"),
        )
        self.assertEqual(result["rtkSource"], "NETWORK_RTK")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_WGS84")
        self.assertEqual(result["referenceEllipsoid"], "WGS84")
        self.assertFalse(result["specDefaultInvoked"])
        self.assertEqual(result["terminalStatus"], "AUTO_PASS")

    def test_i_conflicting_explicit_evidence(self) -> None:
        result = _eval(self.wall, explicit_reference_evidence=_structured("WGS84", "CGCS2000"))
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

    def test_closed_field_tables_are_exact(self) -> None:
        self.assertEqual(
            APPROVED_CAPTURE_FAMILY_FIELDS,
            ("drone-dji:ProductName", "drone-dji:DroneModel", "EXIF:Model"),
        )
        self.assertEqual(
            APPROVED_NETWORK_RTK_OVERRIDE_FIELDS,
            ("NTRIPHost", "NTRIPPort", "NTRIPMountPoint"),
        )
        self.assertEqual(APPROVED_EXPLICIT_REFERENCE_SYSTEM_FIELDS, ())
        self.assertEqual(APPROVED_MATRICE_4_EXIF_MODELS, frozenset({"M4E", "M4T"}))
        self.assertEqual(APPROVED_MATRICE_4_DRONE_MODELS, frozenset({"M4E", "M4T"}))
        self.assertEqual(
            APPROVED_MATRICE_4_PRODUCT_NAMES,
            frozenset({"DJI Matrice 4E", "DJI Matrice 4T"}),
        )
        source = Path(ellipsoid_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("OVERRIDE_TOKEN_RE", source)
        self.assertNotIn("wall_jinshidong", source)
        self.assertNotIn("wall_jiulongfeng", source)
        self.assertNotIn("rglob", source)
        result = evaluate_rule_c(self.wall)
        self.assertFalse(result["recursiveStringSearchAuthorized"])
        self.assertEqual(
            result["closedFieldTables"]["APPROVED_NETWORK_RTK_OVERRIDE_FIELDS"],
            list(APPROVED_NETWORK_RTK_OVERRIDE_FIELDS),
        )

    def test_a11_1_rtk_diff_age_alone_is_not_network_rtk(self) -> None:
        result = _eval(self.wall, extra_xmp={"RtkDiffAge": "2.40000"})
        self.assertEqual(result["rtkSource"], "UNKNOWN")
        self.assertFalse(result["networkRtk"]["detected"])

    def test_a11_2_rtk_flag_50_alone_is_not_network_rtk(self) -> None:
        result = _eval(self.wall, extra_xmp={"RtkFlag": "50"})
        self.assertEqual(result["rtkSource"], "UNKNOWN")
        self.assertFalse(result["networkRtk"]["detected"])

    def test_a11_3_mrk_q_50_alone_is_not_network_rtk(self) -> None:
        result = _eval(self.wall)
        self.assertEqual(result["rtkSource"], "UNKNOWN")
        self.assertFalse(result["networkRtk"]["detected"])

    def test_a11_4_filename_cors_is_not_network_rtk(self) -> None:
        cap = self.wall / "flight"
        dest = cap / "DJI_20260823122200_0001_V.JPG"
        write_jpeg(dest, make="DJI", model="M4E")
        cors = cap / "note_CORS.txt"
        cors.write_text("CORS", encoding="utf-8")
        renamed = cap / "DJI_20260823122200_CORS_0001_V.JPG"
        dest.rename(renamed)
        result = evaluate_rule_c(
            self.wall,
            capture_relative_paths=[renamed.relative_to(self.wall).as_posix()],
            camera_models=["M4E"],
        )
        self.assertEqual(result["rtkSource"], "UNKNOWN")
        self.assertFalse(result["networkRtk"]["detected"])

    def test_a11_5_folder_cgcs2000_is_not_proven_non_wgs84(self) -> None:
        cap = self.wall / "CGCS2000_flight"
        jpg = _dji(cap, 1)
        result = evaluate_rule_c(
            self.wall,
            capture_relative_paths=[jpg.relative_to(self.wall).as_posix()],
            camera_models=["M4E"],
        )
        self.assertNotEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_NON_WGS84")
        self.assertNotEqual(result["referenceEllipsoid"], "CGCS2000")

    def test_a11_6_unrelated_ntrip_text_is_not_network_rtk(self) -> None:
        cap = self.wall / "flight"
        jpg = _dji(cap, 1)
        (cap / "readme.txt").write_text("This note mentions NTRIP and CORS.\n", encoding="utf-8")
        result = evaluate_rule_c(
            self.wall,
            capture_relative_paths=[jpg.relative_to(self.wall).as_posix()],
            camera_models=["M4E"],
        )
        self.assertEqual(result["rtkSource"], "UNKNOWN")
        self.assertFalse(result["networkRtk"]["detected"])

    def test_a11_7_populated_ntrip_host_is_network_rtk(self) -> None:
        result = _eval(self.wall, extra_xmp={"NTRIPHost": "203.0.113.10"})
        self.assertEqual(result["rtkSource"], "NETWORK_RTK")

    def test_a11_8_ntrip_not_present_is_not_network_rtk(self) -> None:
        result = _eval(self.wall)
        self.assertEqual(result["networkRtk"]["fieldsInspected"]["NTRIPHost"]["presence"], "FIELD_NOT_PRESENT")
        self.assertFalse(result["networkRtk"]["detected"])

    def test_a11_9_ntrip_present_empty_is_not_network_rtk(self) -> None:
        result = _eval(self.wall, extra_xmp={"NTRIPHost": ""})
        self.assertEqual(result["networkRtk"]["fieldsInspected"]["NTRIPHost"]["presence"], "FIELD_PRESENT_EMPTY")
        self.assertFalse(result["networkRtk"]["detected"])

    def test_a11_10_product_name_identifies_matrice_4(self) -> None:
        self.assertEqual(
            identify_capture_family(product_name="DJI Matrice 4E"),
            "DJI_MATRICE_4_SERIES",
        )
        result = _eval(self.wall, model="FC6540", extra_xmp={"ProductName": "DJI Matrice 4E"})
        self.assertEqual(result["captureFamily"], "DJI_MATRICE_4_SERIES")

    def test_a11_11_drone_model_identifies_matrice_4(self) -> None:
        self.assertEqual(identify_capture_family(drone_model="M4E"), "DJI_MATRICE_4_SERIES")
        result = _eval(self.wall, model="FC6540", extra_xmp={"DroneModel": "M4E"})
        self.assertEqual(result["captureFamily"], "DJI_MATRICE_4_SERIES")

    def test_a11_12_exif_model_identifies_matrice_4(self) -> None:
        self.assertEqual(identify_capture_family(exif_model="M4E"), "DJI_MATRICE_4_SERIES")
        result = _eval(self.wall, model="M4E")
        self.assertEqual(result["captureFamily"], "DJI_MATRICE_4_SERIES")

    def test_a11_13_wall_id_without_camera_metadata_is_not_matrice_4(self) -> None:
        named = self.tmp / "incoming" / "wall_jinshidong_01"
        named.mkdir(parents=True)
        result = evaluate_rule_c(named)
        self.assertEqual(result["captureFamily"], "UNKNOWN")
        source = Path(ellipsoid_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("wall_jinshidong_01", source)

    def test_a11_14_jiulongfeng_m4e_metadata_is_eligible_without_wall_case(self) -> None:
        result = evaluate_rule_c_session(
            self.wall,
            session_id="synthetic-20260823",
            capture_relative_paths=[],
            camera_models=[],
        )
        # Family comes from session metadata, not wall identity.
        result = _eval(
            self.wall,
            extra_xmp={"ProductName": "DJI Matrice 4E", "DroneModel": "M4E"},
        )
        self.assertEqual(result["captureFamily"], "DJI_MATRICE_4_SERIES")
        source = Path(ellipsoid_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("wall_jiulongfeng_01", source)
        self.assertFalse(result.get("crossSessionFamilyInheritance", False))

    def test_a11_15_gnss_only_session_cannot_borrow_family(self) -> None:
        jpg_session = self.wall / "DJI_202608231218_006"
        _dji(jpg_session, 1, xmp={"ProductName": "DJI Matrice 4E", "DroneModel": "M4E"})
        gnss = self.wall / "rtk_ppk_004"
        mrk = _mrk(gnss, [1])
        parsed = parse_mrk(mrk.read_text(encoding="utf-8"))
        result = evaluate_rule_c_session(
            self.wall,
            session_id="20260812-gnss-only",
            capture_relative_paths=[],
            camera_models=[],
            mrk_relative_path=mrk.relative_to(self.wall).as_posix(),
            mrk_records=parsed["records"],
        )
        self.assertEqual(result["captureFamily"], "UNKNOWN")
        self.assertFalse(result["crossSessionFamilyInheritance"])
        self.assertTrue(result["mrkEllh"]["valid"])

    def test_m4t_is_approved_family(self) -> None:
        self.assertEqual(identify_capture_family(exif_model="M4T"), "DJI_MATRICE_4_SERIES")
        self.assertEqual(identify_capture_family(product_name="DJI Matrice 4T"), "DJI_MATRICE_4_SERIES")
        result = _eval(self.wall, model="M4T")
        self.assertEqual(result["captureFamily"], "DJI_MATRICE_4_SERIES")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC")

    def test_unapproved_matrice4_tokens_are_unknown(self) -> None:
        rejected = [
            {"exif_model": "M4D"},
            {"exif_model": "M4TD"},
            {"exif_model": "M4ET"},
            {"exif_model": "M4"},
            {"product_name": "DJI Matrice 4D"},
            {"product_name": "DJI Matrice 4TD"},
            {"product_name": "DJI Matrice 4 Enterprise"},
            {"product_name": "Survey drone with Matrice 4 payload"},
        ]
        for kwargs in rejected:
            self.assertEqual(identify_capture_family(**kwargs), "UNKNOWN", kwargs)
        result = _eval(self.wall, model="M4D")
        self.assertEqual(result["captureFamily"], "UNKNOWN")
        self.assertFalse(result["specDefaultInvoked"])

    def test_real_xmp_rtk_coordinate_system_is_ignored(self) -> None:
        result = _eval(self.wall, extra_xmp={"RtkCoordinateSystem": "WGS84"})
        self.assertNotEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_WGS84")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC")

    def test_real_xmp_rtk_datum_is_ignored(self) -> None:
        result = _eval(self.wall, extra_xmp={"RtkDatum": "CGCS2000"})
        self.assertNotEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_NON_WGS84")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC")

    def test_real_xmp_rtk_fields_do_not_create_authoritative_conflict(self) -> None:
        result = _eval(
            self.wall,
            extra_xmp={"RtkCoordinateSystem": "WGS84", "RtkDatum": "CGCS2000"},
        )
        self.assertNotEqual(result["referenceEllipsoidProvenanceStatus"], "CONFLICTING_EVIDENCE")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC")

    def test_wall_jiulongfeng_id_cannot_identify_family(self) -> None:
        named = self.tmp / "incoming" / "wall_jiulongfeng_01"
        named.mkdir(parents=True)
        result = evaluate_rule_c(named)
        self.assertEqual(result["captureFamily"], "UNKNOWN")
        source = Path(ellipsoid_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("wall_jiulongfeng_01", source)


if __name__ == "__main__":
    unittest.main()
