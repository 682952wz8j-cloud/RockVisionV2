from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.colmap.source_identity import (
    REASON_AMBIGUOUS,
    REASON_FOREIGN_IMAGE,
    REASON_MODEL_MISMATCH,
    REASON_NOT_PROVEN,
    REASON_PROVEN,
    REASON_SET_MISMATCH,
    SELECTED_MODEL_RELATIVE_PATH,
    STATUS_AUTO_FAIL,
    STATUS_AUTO_PASS,
    STATUS_DGRR,
    STATUS_HUMAN_REVIEW,
    build_provenance_payload,
    evaluate_colmap_source_identity,
    materialize_identity_workspace,
    model_fingerprint,
    write_provenance,
)
from offline.metric_registration.pipeline import register
from offline.stage2_selection.select import select_stage2_inputs
from offline.stage2_selection.sources import Stage2SelectedSources, sources_from_selection
from offline.testdata.ingestion.jpeg_exif import write_jpeg

ORIGIN = (100.0, 200.0, 10.0)
META = "export/terra_ply/metadata.xml"
HEIGHT_SFM = "九龙峰森林站大楼/AT/sfm_geo_desc.json"
HEIGHT_LEGACY_MRK = "dji_flight_raw_jiulongfeng/rtk_ppk_004/DJI_20260812152955_0002_D.MRK"
EXPECTED_SCALE = 3.19764417024824


def _approved_height() -> dict:
    return {
        "referenceEllipsoid": "WGS84",
        "referenceEllipsoidProvenanceStatus": "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC",
        "specDefaultInvoked": True,
        "mrkEllhValid": True,
        "heightObservationSemantic": "GNSS_GEODETIC_ELLIPSOIDAL_HEIGHT",
        "terraVerticalMode": "DEFAULT",
        "geoidConversionConfigured": "NO",
        "verticalOverrideConfigured": "NO",
        "usedSrsOrigin": list(ORIGIN),
        "selectedSrsOrigin": list(ORIGIN),
        "selectedMetadataRelativePath": META,
        "usedMetadataRelativePath": META,
        "terraExportRootRelative": "export",
        "srsOriginProvenanceOk": True,
    }


def _write_model(path: Path, token: bytes) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "images.bin").write_bytes(token)
    (path / "cameras.bin").write_bytes(token + b"-cam")
    (path / "points3D.bin").write_bytes(token + b"-pts")


def _write_jpeg_with_flag(path: Path, flag: str = "50") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_jpeg(path, xmp={"RtkFlag": flag})


class ColmapSourceIdentityEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_csi_"))
        self.wall_id = "wall_test_csi"
        self.incoming = self.tmp / "incoming" / self.wall_id
        self.colmap = self.tmp / "colmap"
        meta = self.incoming / META
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<ModelMetadata version=\"1\">\n"
            "<SRS>EPSG:32650</SRS>\n"
            "<SRSOrigin>100.0,200.0,10.0</SRSOrigin>\n"
            "</ModelMetadata>\n",
            encoding="utf-8",
        )
        self.rels = (
            "flight/DJI_20260823122200_0001_V.JPG",
            "flight/DJI_20260823122200_0002_V.JPG",
            "flight/DJI_20260823122200_0003_V.JPG",
        )
        for rel in self.rels:
            _write_jpeg_with_flag(self.incoming / rel)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sources(self, rels=None, **extra) -> Stage2SelectedSources:
        paths = tuple(rels if rels is not None else self.rels)
        kwargs = dict(
            wall_id=self.wall_id,
            image_relative_paths=paths,
            image_dir_relative="flight",
            mrk_relative_path="flight/x.MRK",
            metadata_xml_relative_path=META,
            srs="EPSG:32650",
            srs_origin=ORIGIN,
            ply_relative_path=None,
            association_method="test",
            association_rule="test",
            height_provenance_evidence=_approved_height(),
            positioning_quality_frames=tuple(
                {
                    "imageRelativePath": rel,
                    "sequence": idx + 1,
                    "rtkFlagOccurrences": ["50"],
                }
                for idx, rel in enumerate(paths)
            ),
        )
        kwargs.update(extra)
        return Stage2SelectedSources(**kwargs)

    def _write_matching_identity(
        self,
        *,
        registered: list[str],
        model_rel: str = SELECTED_MODEL_RELATIVE_PATH,
        token: bytes = b"selected-model",
        rels=None,
        also_write_sparse0: bytes | None = None,
    ) -> Path:
        sources = self._sources(rels)
        from offline.colmap.source_identity import selected_source_snapshot

        paths, hashes, missing = selected_source_snapshot(self.incoming, sources)
        self.assertFalse(missing)
        model_dir = self.colmap / model_rel
        _write_model(model_dir, token)
        if also_write_sparse0 is not None:
            _write_model(self.colmap / "sparse" / "0", also_write_sparse0)
        payload = build_provenance_payload(
            wall_id=self.wall_id,
            selected_relative_paths=paths,
            selected_sha256=hashes,
            selected_model_id=0,
            selected_model_relative_path=model_rel,
            source_model_relative_path="sparse/0",
            registered_image_names=registered,
            model_dir=model_dir,
            image_dir_relative="flight",
        )
        write_provenance(self.colmap, payload)
        return model_dir

    def test_a_exact_selected_source_model_pass(self) -> None:
        registered = [Path(rel).name for rel in self.rels]
        model_dir = self._write_matching_identity(registered=registered)
        result = evaluate_colmap_source_identity(
            self.incoming,
            self._sources(),
            self.colmap,
            registered_image_names=registered,
        )
        self.assertTrue(result["colmapSourceIdentityExecutionAllowed"])
        self.assertEqual(result["colmapSourceIdentityProvenance"], STATUS_AUTO_PASS)
        self.assertEqual(result["colmapSourceIdentityReasonCode"], REASON_PROVEN)
        self.assertEqual(Path(result["resolvedModelPath"]), model_dir.resolve())
        self.assertEqual(result["selectedImageCount"], 3)
        self.assertEqual(result["registeredImageCount"], 3)
        self.assertEqual(result["foreignImageNames"], [])
        self.assertFalse(result["genericStage2Pass"])
        self.assertFalse(result["productionBuildStage2Enabled"])
        self.assertEqual(result["wallMetricMetersProvenance"], "NOT_CLAIMED")

    def test_b_missing_provenance_blocked(self) -> None:
        _write_model(self.colmap / SELECTED_MODEL_RELATIVE_PATH, b"orphan")
        result = evaluate_colmap_source_identity(self.incoming, self._sources(), self.colmap)
        self.assertFalse(result["colmapSourceIdentityExecutionAllowed"])
        self.assertEqual(result["colmapSourceIdentityProvenance"], STATUS_DGRR)
        self.assertEqual(result["colmapSourceIdentityReasonCode"], REASON_NOT_PROVEN)

    def test_c_selected_source_set_changed_blocked(self) -> None:
        registered = [Path(rel).name for rel in self.rels]
        self._write_matching_identity(registered=registered)
        extra = "flight/DJI_20260823122200_0004_V.JPG"
        _write_jpeg_with_flag(self.incoming / extra)
        result = evaluate_colmap_source_identity(
            self.incoming,
            self._sources(self.rels + (extra,)),
            self.colmap,
            registered_image_names=registered,
        )
        self.assertFalse(result["colmapSourceIdentityExecutionAllowed"])
        self.assertEqual(result["colmapSourceIdentityReasonCode"], REASON_SET_MISMATCH)

    def test_d_recorded_model_path_differs_blocked(self) -> None:
        registered = [Path(rel).name for rel in self.rels]
        self._write_matching_identity(registered=registered, model_rel="sparse/best", token=b"best")
        _write_model(self.colmap / "sparse" / "0", b"zero-different")
        from offline.colmap.source_identity import load_provenance

        recorded = load_provenance(self.colmap)
        recorded["selectedModelRelativePath"] = "sparse/0"
        write_provenance(self.colmap, recorded)
        result = evaluate_colmap_source_identity(
            self.incoming,
            self._sources(),
            self.colmap,
            registered_image_names=registered,
        )
        self.assertFalse(result["colmapSourceIdentityExecutionAllowed"])
        self.assertEqual(result["colmapSourceIdentityReasonCode"], REASON_MODEL_MISMATCH)

    def test_e_foreign_colmap_image_auto_fail(self) -> None:
        registered = [Path(self.rels[0]).name, "FOREIGN_IMAGE.JPG"]
        self._write_matching_identity(registered=registered)
        result = evaluate_colmap_source_identity(
            self.incoming,
            self._sources(),
            self.colmap,
            registered_image_names=registered,
        )
        self.assertFalse(result["colmapSourceIdentityExecutionAllowed"])
        self.assertEqual(result["colmapSourceIdentityProvenance"], STATUS_AUTO_FAIL)
        self.assertEqual(result["colmapSourceIdentityReasonCode"], REASON_FOREIGN_IMAGE)
        self.assertIn("FOREIGN_IMAGE.JPG", result["foreignImageNames"])

    def test_f_duplicate_basename_human_review(self) -> None:
        dup_a = "flight/DJI_20260823122200_0001_V.JPG"
        other_dir = self.incoming / "other"
        dup_b_rel = "other/DJI_20260823122200_0001_V.JPG"
        _write_jpeg_with_flag(self.incoming / dup_b_rel)
        result = evaluate_colmap_source_identity(
            self.incoming,
            self._sources((dup_a, dup_b_rel)),
            self.colmap,
        )
        self.assertFalse(result["colmapSourceIdentityExecutionAllowed"])
        self.assertEqual(result["colmapSourceIdentityProvenance"], STATUS_HUMAN_REVIEW)
        self.assertEqual(result["colmapSourceIdentityReasonCode"], REASON_AMBIGUOUS)
        self.assertTrue(other_dir.is_dir())

    def test_g_partial_registration_subset_allowed(self) -> None:
        registered = [Path(self.rels[0]).name, Path(self.rels[1]).name]
        self._write_matching_identity(registered=registered)
        result = evaluate_colmap_source_identity(
            self.incoming,
            self._sources(),
            self.colmap,
            registered_image_names=registered,
        )
        self.assertTrue(result["colmapSourceIdentityExecutionAllowed"])
        self.assertEqual(result["colmapSourceIdentityReasonCode"], REASON_PROVEN)
        self.assertEqual(result["registeredImageCount"], 2)
        self.assertEqual(result["selectedImageCount"], 3)

    def test_h_sparse0_exists_but_selected_is_best(self) -> None:
        registered = [Path(rel).name for rel in self.rels]
        model_dir = self._write_matching_identity(
            registered=registered,
            token=b"authoritative-best",
            also_write_sparse0=b"stale-zero",
        )
        result = evaluate_colmap_source_identity(
            self.incoming,
            self._sources(),
            self.colmap,
            registered_image_names=registered,
        )
        self.assertTrue(result["colmapSourceIdentityExecutionAllowed"])
        self.assertEqual(Path(result["resolvedModelPath"]), model_dir.resolve())
        self.assertTrue(str(result["resolvedModelPath"]).endswith("sparse/best"))
        self.assertNotEqual(
            model_fingerprint(self.colmap / "sparse" / "0"),
            model_fingerprint(model_dir),
        )

    def test_i_selected_model_missing_blocked(self) -> None:
        registered = [Path(rel).name for rel in self.rels]
        self._write_matching_identity(registered=registered)
        shutil.rmtree(self.colmap / SELECTED_MODEL_RELATIVE_PATH)
        result = evaluate_colmap_source_identity(
            self.incoming,
            self._sources(),
            self.colmap,
            registered_image_names=registered,
        )
        self.assertFalse(result["colmapSourceIdentityExecutionAllowed"])
        self.assertEqual(result["colmapSourceIdentityReasonCode"], REASON_MODEL_MISMATCH)


class ColmapSourceIdentityPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_csi_pipe_"))
        self.wall_id = "wall_test_csi_pipe"
        self.incoming = self.tmp / "incoming" / self.wall_id
        meta = self.incoming / META
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<ModelMetadata version=\"1\">\n"
            "<SRS>EPSG:32650</SRS>\n"
            "<SRSOrigin>100.0,200.0,10.0</SRSOrigin>\n"
            "</ModelMetadata>\n",
            encoding="utf-8",
        )
        self.rel = "flight/DJI_20260823122200_0001_V.JPG"
        _write_jpeg_with_flag(self.incoming / self.rel)
        self.dest = self.tmp / "metric_registration"
        self.colmap = self.tmp / "offline" / "work" / self.wall_id / "colmap"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sources(self) -> Stage2SelectedSources:
        return Stage2SelectedSources(
            wall_id=self.wall_id,
            image_relative_paths=(self.rel,),
            image_dir_relative="flight",
            mrk_relative_path="flight/x.MRK",
            metadata_xml_relative_path=META,
            srs="EPSG:32650",
            srs_origin=ORIGIN,
            ply_relative_path=None,
            association_method="test",
            association_rule="test",
            height_provenance_evidence=_approved_height(),
            positioning_quality_frames=(
                {
                    "imageRelativePath": self.rel,
                    "sequence": 1,
                    "rtkFlagOccurrences": ["50"],
                },
            ),
        )

    def test_j_identity_failure_stops_before_correspondences_and_sim3(self) -> None:
        sources = self._sources()
        with patch("offline.metric_registration.pipeline.ransac_umeyama") as ransac, patch(
            "offline.metric_registration.pipeline.umeyama"
        ) as umeyama_fn, patch(
            "offline.metric_registration.pipeline.build_correspondences"
        ) as corr:
            corr.side_effect = RuntimeError("REACHED_CORRESPONDENCES")
            ransac.side_effect = AssertionError("SIM3_CALLED")
            umeyama_fn.side_effect = AssertionError("SIM3_CALLED")
            payload = register(self.wall_id, self.tmp, sources=sources, dest=self.dest)
        corr.assert_not_called()
        umeyama_fn.assert_not_called()
        ransac.assert_not_called()
        self.assertEqual(payload["correspondenceCount"], 0)
        self.assertNotIn("scale", payload)
        self.assertEqual(payload["reasonCode"], REASON_NOT_PROVEN)
        self.assertFalse((self.dest / "S_wall_colmap.json").is_file())
        self.assertFalse((self.dest / "camera_correspondences.json").is_file())
        self.assertFalse(payload["genericStage2Pass"])
        self.assertFalse(payload["productionBuildStage2Enabled"])


class ColmapSourceIdentityRealRegressionTests(unittest.TestCase):
    def test_jiulongfeng_identity_and_scale_against_frozen_model(self) -> None:
        try:
            import pycolmap  # noqa: F401
        except ImportError:
            self.fail("pycolmap is required for Jiulongfeng COLMAP identity regression")
        incoming = ROOT / "incoming" / "wall_jiulongfeng_01"
        frozen = ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "colmap"
        if not incoming.is_dir() or not (frozen / "sparse" / "0" / "images.bin").is_file():
            self.skipTest("Jiulongfeng incoming or frozen COLMAP is not present")
        from offline.tests.test_stage2_regression import frozen_fingerprints

        before = frozen_fingerprints()
        artifact = select_stage2_inputs("wall_jiulongfeng_01", ROOT)
        sources = sources_from_selection(artifact)
        self.assertIsNotNone(sources)
        self.assertEqual(len(sources.image_relative_paths), 47)
        dest_colmap = Path(tempfile.mkdtemp(prefix="rv_csi_jf_id_")) / "colmap"
        dest_metric = Path(tempfile.mkdtemp(prefix="rv_csi_jf_reg_")) / "metric_registration"
        try:
            identity = materialize_identity_workspace(
                incoming=incoming,
                sources=sources,
                source_colmap_dir=frozen,
                dest_colmap_dir=dest_colmap,
            )
            self.assertTrue(identity["colmapSourceIdentityExecutionAllowed"], identity.get("problems"))
            self.assertEqual(identity["colmapSourceIdentityReasonCode"], REASON_PROVEN)
            self.assertEqual(identity["selectedImageCount"], 47)
            self.assertEqual(identity["foreignImageNames"], [])
            self.assertLessEqual(identity["registeredImageCount"], 47)
            self.assertGreater(identity["registeredImageCount"], 0)
            self.assertTrue(str(identity["resolvedModelPath"]).endswith("sparse/best"))
            self.assertFalse((frozen / "colmap_source_identity.json").exists())
            sourced = Stage2SelectedSources(
                **{
                    **sources.__dict__,
                    "height_sfm_geo_desc": HEIGHT_SFM,
                    "height_legacy_mrk": HEIGHT_LEGACY_MRK,
                }
            )
            payload = register(
                "wall_jiulongfeng_01",
                ROOT,
                sources=sourced,
                dest=dest_metric,
                colmap_dir=dest_colmap,
            )
            self.assertEqual(payload["colmapSourceIdentityReasonCode"], REASON_PROVEN)
            self.assertTrue(payload["colmapSourceIdentityExecutionAllowed"])
            self.assertAlmostEqual(payload["scale"], EXPECTED_SCALE, places=9)
            self.assertEqual(payload["outputFrame"], "WallLocal")
            self.assertEqual(payload["wallMetricMetersProvenance"], "NOT_CLAIMED")
            self.assertFalse(payload["genericStage2Pass"])
            self.assertFalse(payload["productionBuildStage2Enabled"])
        finally:
            shutil.rmtree(dest_colmap.parent, ignore_errors=True)
            shutil.rmtree(dest_metric.parent, ignore_errors=True)
        self.assertEqual(frozen_fingerprints(), before)

    def test_jiulongfeng_wrong_model_stops_before_sim3(self) -> None:
        try:
            import pycolmap  # noqa: F401
        except ImportError:
            self.fail("pycolmap is required for wrong-model identity regression")
        incoming = ROOT / "incoming" / "wall_jiulongfeng_01"
        frozen = ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "colmap"
        if not incoming.is_dir() or not (frozen / "sparse" / "0" / "images.bin").is_file():
            self.skipTest("Jiulongfeng incoming or frozen COLMAP is not present")
        from offline.tests.test_stage2_regression import frozen_fingerprints

        before = frozen_fingerprints()
        artifact = select_stage2_inputs("wall_jiulongfeng_01", ROOT)
        sources = sources_from_selection(artifact)
        dest_colmap = Path(tempfile.mkdtemp(prefix="rv_csi_wrong_")) / "colmap"
        dest_metric = Path(tempfile.mkdtemp(prefix="rv_csi_wrong_reg_")) / "metric_registration"
        try:
            identity = materialize_identity_workspace(
                incoming=incoming,
                sources=sources,
                source_colmap_dir=frozen,
                dest_colmap_dir=dest_colmap,
            )
            self.assertTrue(identity["colmapSourceIdentityExecutionAllowed"])
            tampered = dest_colmap / SELECTED_MODEL_RELATIVE_PATH / "images.bin"
            tampered.write_bytes(tampered.read_bytes() + b"\x00WRONG")
            with patch("offline.metric_registration.pipeline.ransac_umeyama") as ransac, patch(
                "offline.metric_registration.pipeline.umeyama"
            ) as umeyama_fn, patch(
                "offline.metric_registration.pipeline.build_correspondences"
            ) as corr:
                corr.side_effect = RuntimeError("REACHED_CORRESPONDENCES")
                payload = register(
                    "wall_jiulongfeng_01",
                    ROOT,
                    sources=sources,
                    dest=dest_metric,
                    colmap_dir=dest_colmap,
                )
            corr.assert_not_called()
            umeyama_fn.assert_not_called()
            ransac.assert_not_called()
            self.assertEqual(payload["reasonCode"], REASON_MODEL_MISMATCH)
            self.assertEqual(payload["correspondenceCount"], 0)
            self.assertNotIn("scale", payload)
            self.assertFalse((dest_metric / "S_wall_colmap.json").is_file())
        finally:
            shutil.rmtree(dest_colmap.parent, ignore_errors=True)
            shutil.rmtree(dest_metric.parent, ignore_errors=True)
        self.assertEqual(frozen_fingerprints(), before)


if __name__ == "__main__":
    unittest.main()
