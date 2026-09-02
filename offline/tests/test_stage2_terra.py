from __future__ import annotations

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
from offline.stage2_selection.select import select_stage2_inputs
from offline.stage2_selection.terra import has_exact_temp_component
from offline.testdata.ingestion.jpeg_exif import write_jpeg

WALL = "wall_test_terra"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _dji(path: Path, seq: int, date: str = "20260823", time: str = "122200") -> Path:
    dest = path / f"DJI_{date}{time}_{seq:04d}_V.JPG"
    write_jpeg(dest, make="DJI", model="M4E")
    return dest


def _mrk(path: Path, photo_ids: list[int], name: str = "DJI_20260823122200_0002_D.MRK") -> Path:
    lines = [
        f"{pid}\t100.0\t[2433]\t0,N\t0,E\t0,V\t30.13000000,Lat\t118.01500000,Lon\t350.000,Ellh\t50,Q"
        for pid in photo_ids
    ]
    dest = path / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def _metadata(
    path: Path,
    *,
    srs: str = "EPSG:32650",
    origin: str = "100.0,200.0,10.0",
    extra: str = "",
) -> Path:
    dest = path / "metadata.xml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ModelMetadata version="1">\n'
        f"<SRS>{srs}</SRS>\n"
        f"<SRSOrigin>{origin}</SRSOrigin>\n"
        f"{extra}"
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


def _capture(wall: Path) -> None:
    cap = wall / "flight"
    _dji(cap, 1)
    _mrk(cap, [1])


class Stage2TerraProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_s2_terra_"))
        self.wall = self.tmp / "incoming" / WALL
        self.wall.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _select(self) -> dict:
        return select_stage2_inputs(WALL, self.tmp)

    def test_no_terra_export_root_auto_fail(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "models")
        _ply(self.wall / "models")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("TERRA_PLY_PRODUCT_NOT_PROVEN", artifact["selectionReasonCodes"])

    def test_multiple_terra_export_roots_human_review(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "aaa" / "terra_ply")
        _ply(self.wall / "aaa" / "terra_ply")
        _metadata(self.wall / "zzz" / "terra_ply")
        _ply(self.wall / "zzz" / "terra_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "HUMAN_REVIEW_REQUIRED")
        self.assertIn("MULTIPLE_TERRA_EXPORT_ROOTS", artifact["selectionReasonCodes"])
        self.assertIsNone(artifact["terraExportRoot"])
        self.assertIsNone(artifact["selectedModelSpatialMetadata"])

    def test_no_valid_metadata_auto_fail(self) -> None:
        _capture(self.wall)
        _ply(self.wall / "export" / "terra_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("NO_VALID_TERRA_METADATA", artifact["selectionReasonCodes"])

    def test_malformed_metadata_only_auto_fail(self) -> None:
        _capture(self.wall)
        _write(
            self.wall / "export" / "terra_ply" / "metadata.xml",
            "<ModelMetadata><SRS>EPSG:32650</SRS><SRSOrigin>nope</SRSOrigin></ModelMetadata>\n",
        )
        _ply(self.wall / "export" / "terra_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("NO_VALID_TERRA_METADATA", artifact["selectionReasonCodes"])
        copies = artifact["terraMetadataCopies"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]["parseStatus"], "malformed")

    def test_valid_plus_malformed_metadata_development_gate(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply")
        _write(
            self.wall / "export" / "terra_obj" / "metadata.xml",
            "<ModelMetadata><SRS>EPSG:32650</SRS><SRSOrigin>bad</SRSOrigin></ModelMetadata>\n",
        )
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertIn("MALFORMED_TERRA_METADATA_PRESENT", artifact["selectionReasonCodes"])
        self.assertIsNone(artifact["selectedModelSpatialMetadata"])

    def test_equivalent_duplicate_metadata_one_frame(self) -> None:
        _capture(self.wall)
        extra = "<Texture><ColorSource>Visible</ColorSource></Texture>\n"
        _metadata(self.wall / "export" / "terra_point_ply", extra=extra)
        _metadata(self.wall / "export" / "terra_obj", extra=extra)
        _ply(self.wall / "export" / "terra_point_ply", name="cloud.ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(len(artifact["terraMetadataCopies"]), 2)
        self.assertTrue(all(c["equivalenceStatus"] == "equivalent" for c in artifact["terraMetadataCopies"]))
        self.assertEqual(artifact["terraSpatialFrame"]["copyCount"], 2)
        self.assertFalse(artifact["terraSpatialFrame"]["byteIdentityRequired"])
        self.assertTrue(artifact["selectionEvidence"]["geometryIsNotFrameProvenance"])
        self.assertEqual(artifact["selectedCrosscheckProduct"]["productToken"], "terra_point_ply")
        self.assertTrue(
            artifact["selectedModelSpatialMetadata"]["relativePath"].startswith("export/terra_point_ply/")
        )

    def test_conflicting_srs_auto_fail(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_ply", srs="EPSG:32650")
        _metadata(self.wall / "export" / "terra_obj", srs="EPSG:32651")
        _ply(self.wall / "export" / "terra_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("TERRA_SPATIAL_FRAME_CONFLICT", artifact["selectionReasonCodes"])

    def test_conflicting_srsorigin_auto_fail(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_ply", origin="100.0,200.0,10.0")
        _metadata(self.wall / "export" / "terra_obj", origin="100.0,200.0,11.0")
        _ply(self.wall / "export" / "terra_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("TERRA_SPATIAL_FRAME_CONFLICT", artifact["selectionReasonCodes"])

    def test_non_epsg_32650_development_gate(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_ply", srs="EPSG:32651")
        _ply(self.wall / "export" / "terra_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertIn("UNSUPPORTED_TERRA_SRS", artifact["selectionReasonCodes"])
        self.assertEqual(artifact["terraSpatialFrame"]["srs"], "EPSG:32651")

    def test_exact_temp_path_excluded(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply", name="keep.ply")
        _ply(self.wall / "export" / ".temp" / "Reconstruction3d" / "cloud_dense.ply")
        _metadata(self.wall / "export" / ".temp" / "metadata.xml")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        selected = artifact["selectedModelSource"]["relativePath"]
        self.assertEqual(selected, "export/terra_ply/keep.ply")
        self.assertFalse(has_exact_temp_component(selected))
        intermediates = artifact["intermediateCandidates"]
        self.assertTrue(intermediates)
        self.assertEqual(intermediates[0]["classification"], "NON_DELIVERABLE_INTERMEDIATE")
        temp_geom = intermediates[0]["geometryCandidates"]
        self.assertTrue(any("cloud_dense.ply" in item["relativePath"] for item in temp_geom))
        self.assertFalse(any(".temp" in (c.get("relativePath") or "") for c in artifact["terraMetadataCopies"]))

    def test_directory_named_temp_not_excluded(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "temp" / "terra_ply")
        _ply(self.wall / "temp" / "terra_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(artifact["terraExportRoot"]["relativePath"], "temp")
        self.assertFalse(has_exact_temp_component("temp/terra_ply/cloud.ply"))

    def test_directory_named_cache_not_excluded(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "cache" / "terra_ply")
        _ply(self.wall / "cache" / "terra_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(artifact["terraExportRoot"]["relativePath"], "cache")

    def test_unknown_terra_product_development_gate(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply")
        (self.wall / "export" / "terra_unknown").mkdir(parents=True)
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertIn("UNKNOWN_TERRA_PRODUCT_TYPE", artifact["selectionReasonCodes"])
        self.assertIsNone(artifact["selectedCrosscheckProduct"])

    def test_zero_crosscheck_products_development_gate(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_obj")
        (self.wall / "export" / "terra_obj" / "BlockR").mkdir(parents=True)
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertIn("GEOMETRY_CROSSCHECK_NOT_AVAILABLE", artifact["selectionReasonCodes"])

    def test_multiple_crosscheck_products_development_gate(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_ply")
        _metadata(self.wall / "export" / "terra_point_ply")
        _ply(self.wall / "export" / "terra_ply", name="mesh.ply")
        _ply(self.wall / "export" / "terra_point_ply", name="cloud.ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        self.assertIn("TERRA_PLY_PRODUCT_AMBIGUOUS", artifact["selectionReasonCodes"])
        self.assertIsNone(artifact["selectedCrosscheckProduct"])
        self.assertIsNone(artifact["selectedModelSource"])

    def test_nested_legal_ply_under_terra_ply(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply" / "BlockR", name="mesh.ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(
            artifact["selectedCrosscheckGeometry"]["relativePath"],
            "export/terra_ply/BlockR/mesh.ply",
        )
        self.assertEqual(artifact["selectedCrosscheckProduct"]["productClass"], "MESH_PLY")

    def test_direct_child_legal_ply_under_terra_point_ply(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_point_ply")
        _ply(self.wall / "export" / "terra_point_ply", name="cloud.ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(
            artifact["selectedCrosscheckGeometry"]["relativePath"],
            "export/terra_point_ply/cloud.ply",
        )
        self.assertEqual(artifact["selectedCrosscheckProduct"]["productClass"], "POINT_CLOUD_PLY")

    def test_temp_ply_never_selected(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply", name="keep.ply")
        _ply(self.wall / "export" / ".temp" / "aaa.ply")
        _ply(self.wall / "export" / ".temp" / "zzz.ply")
        artifact = self._select()
        self.assertEqual(artifact["selectedModelSource"]["relativePath"], "export/terra_ply/keep.ply")
        self.assertFalse(
            any(
                has_exact_temp_component(item["relativePath"])
                for item in artifact["modelCandidates"]
            )
        )

    def test_multiple_equivalent_metadata_does_not_require_geometry_pairing(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_point_ply")
        _metadata(self.wall / "export" / "terra_obj")
        _ply(self.wall / "export" / "terra_point_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(artifact["terraSpatialFrame"]["copyCount"], 2)
        self.assertTrue(artifact["selectedModelSpatialMetadata"]["representativeEquivalentCopy"])
        self.assertTrue(artifact["selectionEvidence"]["geometryIsNotFrameProvenance"])

    def test_origin_compatibility_never_upgrades_provenance(self) -> None:
        _capture(self.wall)
        _ply(self.wall / "export" / "terra_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_FAIL")
        check = origin_compatible_with_mrk(np.array([0.0, 0.0, 0.0]), [np.array([1.0, 1.0, 1.0])])
        self.assertTrue(check["compatible"])
        self.assertFalse(check["isCaptureModelProvenanceProof"])
        self.assertFalse(artifact["originCompatibilityIsProvenanceProof"])
        self.assertNotEqual(artifact["selectionStatus"], "AUTO_PASS")

    def test_lexical_order_does_not_change_selection(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_obj")
        _metadata(self.wall / "export" / "terra_point_ply")
        _ply(self.wall / "export" / "terra_point_ply", name="cloud.ply")
        first = self._select()
        shutil.rmtree(self.wall / "export")
        _metadata(self.wall / "export" / "terra_point_ply")
        _metadata(self.wall / "export" / "terra_obj")
        _ply(self.wall / "export" / "terra_point_ply", name="cloud.ply")
        second = self._select()
        self.assertEqual(first["selectionStatus"], "AUTO_PASS")
        self.assertEqual(second["selectionStatus"], first["selectionStatus"])
        self.assertEqual(second["selectedCrosscheckGeometry"]["relativePath"], first["selectedCrosscheckGeometry"]["relativePath"])
        self.assertEqual(second["terraSpatialFrame"]["srs"], first["terraSpatialFrame"]["srs"])
        self.assertEqual(second["terraSpatialFrame"]["srsOrigin"], first["terraSpatialFrame"]["srsOrigin"])
        self.assertEqual(
            second["selectedModelSpatialMetadata"]["relativePath"],
            first["selectedModelSpatialMetadata"]["relativePath"],
        )

    def test_export_root_not_required_to_be_named_zero(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "recon_job" / "terra_ply")
        _ply(self.wall / "recon_job" / "terra_ply")
        artifact = self._select()
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(artifact["terraExportRoot"]["relativePath"], "recon_job")
        self.assertTrue(artifact["terraExportRootEvidence"]["directoryNameZeroNotRequired"])

    def test_ply_used_in_fit_is_false(self) -> None:
        _capture(self.wall)
        _metadata(self.wall / "export" / "terra_ply")
        _ply(self.wall / "export" / "terra_ply")
        artifact = self._select()
        self.assertFalse(artifact["selectedModelSource"]["usedInFit"])
        self.assertFalse(artifact["selectionEvidence"]["plyUsedInFit"])


class JinshidongReadOnlySelectionTests(unittest.TestCase):
    def test_jinshidong_generic_selection_and_folder_token_is_not_wall_id(self) -> None:
        incoming = ROOT / "incoming" / "wall_jinshidong_01"
        self.assertTrue(incoming.is_dir())
        before = [
            (p.relative_to(incoming).as_posix(), p.stat().st_mtime_ns, p.stat().st_size)
            for p in sorted(incoming.rglob("*"))
            if p.is_file() and p.name != ".DS_Store"
        ]
        artifact = select_stage2_inputs("wall_jinshidong_01", ROOT)
        after = [
            (p.relative_to(incoming).as_posix(), p.stat().st_mtime_ns, p.stat().st_size)
            for p in sorted(incoming.rglob("*"))
            if p.is_file() and p.name != ".DS_Store"
        ]
        self.assertEqual(before, after)
        self.assertEqual(artifact["wallId"], "wall_jinshidong_01")
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        self.assertEqual(artifact["selectedCapture"]["memberCount"], 179)
        self.assertEqual(artifact["selectedMRKSource"]["recordCount"], 179)
        self.assertIn("九龙峰", artifact["selectedCapture"]["parentDirectory"])
        self.assertNotIn("九龙峰", artifact["wallId"])
        self.assertEqual(artifact["terraExportRoot"]["relativePath"], "0")
        self.assertEqual(artifact["terraSpatialFrame"]["srs"], "EPSG:32650")
        self.assertEqual(len(artifact["terraMetadataCopies"]), 2)
        self.assertTrue(all(c["equivalenceStatus"] == "equivalent" for c in artifact["terraMetadataCopies"]))
        self.assertTrue(artifact["terraSpatialFrame"]["copiesByteIdentical"])
        self.assertEqual(artifact["selectedCrosscheckProduct"]["productToken"], "terra_point_ply")
        self.assertEqual(
            artifact["selectedCrosscheckGeometry"]["relativePath"],
            "0/terra_point_ply/cloudR.ply",
        )
        self.assertFalse(artifact["selectedCrosscheckGeometry"]["usedInFit"])
        self.assertTrue(artifact["intermediateCandidates"])
        self.assertTrue(
            any(
                has_exact_temp_component(item["relativePath"])
                for item in artifact["intermediateCandidates"]
            )
        )
        self.assertFalse(
            has_exact_temp_component(artifact["selectedCrosscheckGeometry"]["relativePath"])
        )
        self.assertEqual(artifact["outputFrame"], "WallLocal")
        self.assertEqual(artifact["wallMetricMetersProvenance"], "NOT_CLAIMED")
        self.assertEqual(artifact["heightVerticalDatumProvenance"], "SEPARATE_DEVELOPMENT_GATE")
        self.assertFalse(artifact["selectionEvidence"]["frozenIdentityRegressionEvidenceApplied"])


if __name__ == "__main__":
    unittest.main()
