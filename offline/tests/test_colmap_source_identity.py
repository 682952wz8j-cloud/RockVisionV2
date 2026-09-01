from __future__ import annotations

import json
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
    PROVENANCE_ORIGIN_NOT_AUTHORITATIVE,
    PROVENANCE_ORIGIN_RECONSTRUCTION_RUN,
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
    load_provenance,
    model_fingerprint,
    write_generic_reconstruct_provenance,
    write_provenance,
)
from offline.colmap.pipeline import reconstruct
from offline.metric_registration.pipeline import register
from offline.stage2_selection.select import select_stage2_inputs
from offline.stage2_selection.sources import Stage2SelectedSources, sources_from_selection
from offline.testdata.ingestion.jpeg_exif import write_jpeg

ORIGIN = (100.0, 200.0, 10.0)
META = "export/terra_ply/metadata.xml"


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
            provenance_origin=PROVENANCE_ORIGIN_RECONSTRUCTION_RUN,
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
        self.assertTrue(result["genericStage2Pass"])
        self.assertTrue(result["productionBuildStage2Enabled"])
        self.assertEqual(result["wallMetricMetersProvenance"], "NOT_CLAIMED")

    def test_a_legacy_hash_filename_synthesis_is_not_proven(self) -> None:
        registered = [Path(rel).name for rel in self.rels]
        sources = self._sources()
        from offline.colmap.source_identity import selected_source_snapshot

        paths, hashes, missing = selected_source_snapshot(self.incoming, sources)
        self.assertFalse(missing)
        model_dir = self.colmap / SELECTED_MODEL_RELATIVE_PATH
        _write_model(model_dir, b"legacy-model")
        payload = build_provenance_payload(
            wall_id=self.wall_id,
            selected_relative_paths=paths,
            selected_sha256=hashes,
            selected_model_id=0,
            selected_model_relative_path=SELECTED_MODEL_RELATIVE_PATH,
            source_model_relative_path="sparse/0",
            registered_image_names=registered,
            model_dir=model_dir,
            image_dir_relative="flight",
        )
        self.assertEqual(payload["provenanceOrigin"], PROVENANCE_ORIGIN_NOT_AUTHORITATIVE)
        write_provenance(self.colmap, payload)
        result = evaluate_colmap_source_identity(
            self.incoming,
            sources,
            self.colmap,
            registered_image_names=registered,
        )
        self.assertFalse(result["colmapSourceIdentityExecutionAllowed"])
        self.assertEqual(result["colmapSourceIdentityReasonCode"], REASON_NOT_PROVEN)
        self.assertEqual(result["colmapSourceIdentityProvenance"], STATUS_DGRR)

    def test_c_reconstruction_writer_is_authoritative(self) -> None:
        registered = [Path(rel).name for rel in self.rels]
        sources = self._sources()
        from offline.colmap.source_identity import selected_source_snapshot

        paths, hashes, missing = selected_source_snapshot(self.incoming, sources)
        self.assertFalse(missing)
        _write_model(self.colmap / SELECTED_MODEL_RELATIVE_PATH, b"recon-run")
        written = write_generic_reconstruct_provenance(
            dest=self.colmap,
            wall_id=self.wall_id,
            selected_relative_paths=list(paths),
            selected_sha256=hashes,
            selected_model_id=0,
            registered_image_names=registered,
            image_dir_relative="flight",
            source_model_relative_path="sparse/0",
        )
        self.assertIsNotNone(written)
        self.assertEqual(written["provenanceOrigin"], PROVENANCE_ORIGIN_RECONSTRUCTION_RUN)
        result = evaluate_colmap_source_identity(
            self.incoming,
            sources,
            self.colmap,
            registered_image_names=registered,
        )
        self.assertTrue(result["colmapSourceIdentityExecutionAllowed"])
        self.assertEqual(result["colmapSourceIdentityReasonCode"], REASON_PROVEN)

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

    def test_d_changed_jpeg_bytes_after_reconstruction_blocked(self) -> None:
        registered = [Path(rel).name for rel in self.rels]
        self._write_matching_identity(registered=registered)
        path = self.incoming / self.rels[0]
        path.write_bytes(path.read_bytes() + b"\x00TAMPER")
        result = evaluate_colmap_source_identity(
            self.incoming,
            self._sources(),
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

    def test_e_changed_selected_model_bytes_blocked(self) -> None:
        registered = [Path(rel).name for rel in self.rels]
        self._write_matching_identity(registered=registered, token=b"original-model")
        tampered = self.colmap / SELECTED_MODEL_RELATIVE_PATH / "images.bin"
        tampered.write_bytes(tampered.read_bytes() + b"TAMPER")
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
        self.assertTrue(payload["genericStage2Pass"])
        self.assertTrue(payload["productionBuildStage2Enabled"])


class ColmapSourceIdentityRealRegressionTests(unittest.TestCase):
    def test_b_frozen_jiulongfeng_colmap_is_not_source_identity_proof(self) -> None:
        incoming = ROOT / "incoming" / "wall_jiulongfeng_01"
        frozen = ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "colmap"
        if not incoming.is_dir() or not (frozen / "sparse" / "0" / "images.bin").is_file():
            self.skipTest("Jiulongfeng incoming or frozen COLMAP is not present")
        from offline.tests.test_stage2_regression import frozen_fingerprints

        before = frozen_fingerprints()
        artifact = select_stage2_inputs("wall_jiulongfeng_01", ROOT)
        sources = sources_from_selection(artifact)
        self.assertIsNotNone(sources)
        dest = Path(tempfile.mkdtemp(prefix="rv_csi_frozen_")) / "metric_registration"
        try:
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
                    dest=dest,
                    colmap_dir=frozen,
                )
            corr.assert_not_called()
            umeyama_fn.assert_not_called()
            ransac.assert_not_called()
            self.assertEqual(payload["reasonCode"], REASON_NOT_PROVEN)
            self.assertEqual(payload["correspondenceCount"], 0)
            self.assertNotIn("scale", payload)
            self.assertFalse((dest / "S_wall_colmap.json").is_file())
            self.assertFalse((frozen / "colmap_source_identity.json").exists())
        finally:
            shutil.rmtree(dest.parent, ignore_errors=True)
        self.assertEqual(frozen_fingerprints(), before)

    def test_jiulongfeng_reconstruct_selected_identity_and_register(self) -> None:
        try:
            import pycolmap  # noqa: F401
        except ImportError:
            self.fail("pycolmap is required for Jiulongfeng reconstruct-selected identity")
        incoming = ROOT / "incoming" / "wall_jiulongfeng_01"
        if not incoming.is_dir():
            self.skipTest("incoming/wall_jiulongfeng_01 not present")
        from offline.tests.test_stage2_regression import frozen_fingerprints

        before = frozen_fingerprints()
        artifact = select_stage2_inputs("wall_jiulongfeng_01", ROOT)
        sources = sources_from_selection(artifact)
        self.assertIsNotNone(sources)
        self.assertEqual(len(sources.image_relative_paths), 47)
        workspace = Path(tempfile.mkdtemp(prefix="rv_csi_recon_"))
        dest_colmap = workspace / "colmap"
        dest_metric = workspace / "metric_registration"
        try:
            recon = reconstruct("wall_jiulongfeng_01", ROOT, sources=sources, dest=dest_colmap)
            provenance = load_provenance(dest_colmap)
            identity = evaluate_colmap_source_identity(incoming, sources, dest_colmap)
            if not identity.get("colmapSourceIdentityExecutionAllowed"):
                self.fail(
                    "REAL_RECONSTRUCTION_BLOCKED source identity "
                    f"gate={recon.get('gateResult')} "
                    f"registered={recon.get('registeredImages')} "
                    f"identity={identity.get('colmapSourceIdentityReasonCode')} "
                    f"problems={identity.get('problems')} "
                    f"recon_errors={recon.get('errors')}"
                )
            self.assertEqual(identity["colmapSourceIdentityReasonCode"], REASON_PROVEN)
            self.assertEqual(identity["selectedImageCount"], 47)
            self.assertEqual(identity["foreignImageNames"], [])
            self.assertGreater(identity["registeredImageCount"], 0)
            self.assertLessEqual(identity["registeredImageCount"], 47)
            self.assertEqual(provenance.get("provenanceOrigin"), PROVENANCE_ORIGIN_RECONSTRUCTION_RUN)
            self.assertEqual(provenance.get("selectedImageCount"), 47)
            self.assertEqual(set(provenance.get("selectedImageRelativePaths") or []), set(sources.image_relative_paths))
            self.assertTrue(str(identity["resolvedModelPath"]).endswith("sparse/best"))
            self.assertFalse((ROOT / "offline" / "work" / "wall_jiulongfeng_01" / "colmap" / "colmap_source_identity.json").exists())

            payload = register(
                "wall_jiulongfeng_01",
                ROOT,
                sources=sources,
                dest=dest_metric,
                colmap_dir=dest_colmap,
            )
            print(
                "JIULONGFENG_RECONSTRUCT_SELECTED_SUMMARY "
                f"reconGate={recon.get('gateResult')} "
                f"sourceImages={recon.get('sourceImages')} "
                f"registeredImages={recon.get('registeredImages')} "
                f"unregistered={recon.get('unregisteredImagesCount')} "
                f"identity={identity.get('colmapSourceIdentityReasonCode')} "
                f"identityRegistered={identity.get('registeredImageCount')} "
                f"registerGate={payload.get('gateResult')} "
                f"validation={payload.get('validationStatus')} "
                f"correspondenceCount={payload.get('correspondenceCount')} "
                f"scale={payload.get('scale')} "
                f"holdout={payload.get('holdoutMetrics')} "
                f"outputFrame={payload.get('outputFrame')} "
                f"provenanceOrigin={provenance.get('provenanceOrigin')} "
                f"selectedModel={identity.get('selectedModelRelativePath')}"
            )
            if payload.get("gateResult") not in {"PASS", "NEEDS REVIEW"} or "scale" not in payload:
                self.fail(
                    "REAL_RECONSTRUCTION_BLOCKED register "
                    f"gate={payload.get('gateResult')} "
                    f"validation={payload.get('validationStatus')} "
                    f"reason={payload.get('reasonCode')} "
                    f"problems={payload.get('problems')} "
                    f"errors={payload.get('errors')} "
                    f"registered={recon.get('registeredImages')} "
                    f"correspondenceCount={payload.get('correspondenceCount')}"
                )
            self.assertEqual(payload["colmapSourceIdentityReasonCode"], REASON_PROVEN)
            self.assertTrue(payload["colmapSourceIdentityExecutionAllowed"])
            self.assertEqual(payload["outputFrame"], "WallLocal")
            self.assertEqual(payload["wallMetricMetersProvenance"], "NOT_CLAIMED")
            self.assertTrue(payload["genericStage2Pass"])
            self.assertTrue(payload["productionBuildStage2Enabled"])
            self.assertIsNotNone(payload.get("scale"))
            audit_dir = (
                ROOT
                / "offline"
                / "work"
                / "wall_jiulongfeng_01"
                / "stage2_dev"
                / "colmap_source_identity_real"
            )
            audit_dir.mkdir(parents=True, exist_ok=True)
            summary = {
                "recon": {
                    "gateResult": recon.get("gateResult"),
                    "sourceImages": recon.get("sourceImages"),
                    "registeredImages": recon.get("registeredImages"),
                    "unregisteredImagesCount": recon.get("unregisteredImagesCount"),
                },
                "provenance": {
                    "provenanceOrigin": provenance.get("provenanceOrigin"),
                    "selectedImageCount": provenance.get("selectedImageCount"),
                    "registeredImageCount": provenance.get("registeredImageCount"),
                    "selectedModelRelativePath": provenance.get("selectedModelRelativePath"),
                    "modelFingerprint": provenance.get("modelFingerprint"),
                    "generatedAt": provenance.get("generatedAt"),
                },
                "register": {
                    "gateResult": payload.get("gateResult"),
                    "validationStatus": payload.get("validationStatus"),
                    "reasonCode": payload.get("reasonCode"),
                    "correspondenceCount": payload.get("correspondenceCount"),
                    "scale": payload.get("scale"),
                    "holdoutMetrics": payload.get("holdoutMetrics"),
                    "outputFrame": payload.get("outputFrame"),
                    "colmapSourceIdentityReasonCode": payload.get("colmapSourceIdentityReasonCode"),
                    "colmapSourceIdentityExecutionAllowed": payload.get(
                        "colmapSourceIdentityExecutionAllowed"
                    ),
                    "wallMetricMetersProvenance": payload.get("wallMetricMetersProvenance"),
                    "genericStage2Pass": payload.get("genericStage2Pass"),
                    "productionBuildStage2Enabled": payload.get("productionBuildStage2Enabled"),
                },
            }
            (audit_dir / "last_run_summary.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            identity_src = dest_colmap / "colmap_source_identity.json"
            if identity_src.is_file():
                shutil.copy2(identity_src, audit_dir / "colmap_source_identity.json")
            recon_metrics = dest_colmap / "reconstruction_metrics.json"
            if recon_metrics.is_file():
                shutil.copy2(recon_metrics, audit_dir / "reconstruction_metrics.json")
            metrics_src = dest_metric / "metric_registration_metrics.json"
            if metrics_src.is_file():
                shutil.copy2(metrics_src, audit_dir / "metric_registration_metrics.json")
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
        self.assertEqual(frozen_fingerprints(), before)


if __name__ == "__main__":
    unittest.main()
