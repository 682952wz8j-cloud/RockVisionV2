from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.metric_registration.pipeline import register
from offline.metric_registration.positioning_quality import (
    POSITIONING_QUALITY_GATE_IMPLEMENTATION_IMPLEMENTED,
    POSITIONING_QUALITY_GATE_PASS,
    POSITIONING_QUALITY_POLICY_VERSION,
    REASON_CONFLICT,
    REASON_FIXED,
    REASON_NOT_PROVEN,
    REASON_NOT_SUPPORTED,
    TIER_2_ENABLED,
    collect_positioning_quality_frames,
    evaluate_positioning_quality_from_sources,
    evaluate_positioning_quality_v1,
)
from offline.stage2_selection.select import select_stage2_inputs
from offline.stage2_selection.sources import Stage2SelectedSources, sources_from_selection
from offline.testdata.ingestion.jpeg_exif import write_jpeg

ORIGIN = (100.0, 200.0, 10.0)
META = "export/terra_ply/metadata.xml"


def _frame(rel: str, flag, *, seq: int = 1, **extra) -> dict:
    if flag is None:
        occ: list[str] = []
    elif isinstance(flag, list):
        occ = [str(item) for item in flag]
    else:
        occ = [str(flag)]
    payload = {
        "imageRelativePath": rel,
        "sequence": seq,
        "rtkFlagOccurrences": occ,
    }
    payload.update(extra)
    return payload


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


class PositioningQualityEvaluatorTests(unittest.TestCase):
    def test_a_all_frames_flag_50_auto_pass(self) -> None:
        result = evaluate_positioning_quality_v1(
            [_frame("a.jpg", "50", seq=1), _frame("b.jpg", "50", seq=2)]
        )
        self.assertEqual(result["positioningQualityProvenance"], "AUTO_PASS")
        self.assertEqual(result["positioningQualityReasonCode"], REASON_FIXED)
        self.assertTrue(result["positioningQualityExecutionAllowed"])
        self.assertEqual(result["selectedFrameCount"], 2)
        self.assertEqual(result["fixedFrameCount"], 2)
        self.assertEqual(result["policyVersion"], POSITIONING_QUALITY_POLICY_VERSION)
        self.assertFalse(TIER_2_ENABLED)
        self.assertFalse(POSITIONING_QUALITY_GATE_PASS)
        self.assertTrue(POSITIONING_QUALITY_GATE_IMPLEMENTATION_IMPLEMENTED)

    def test_b_single_flag_16_not_supported(self) -> None:
        result = evaluate_positioning_quality_v1([_frame("a.jpg", "16")])
        self.assertEqual(result["positioningQualityProvenance"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_SUPPORTED)
        self.assertFalse(result["positioningQualityExecutionAllowed"])

    def test_c_flag_0_not_supported(self) -> None:
        result = evaluate_positioning_quality_v1([_frame("a.jpg", "0")])
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_SUPPORTED)

    def test_d_flag_32_not_supported(self) -> None:
        result = evaluate_positioning_quality_v1([_frame("a.jpg", "32")])
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_SUPPORTED)

    def test_e_flag_49_not_supported(self) -> None:
        result = evaluate_positioning_quality_v1([_frame("a.jpg", "49")])
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_SUPPORTED)

    def test_f_missing_rtkflag_not_proven(self) -> None:
        result = evaluate_positioning_quality_v1([_frame("a.jpg", None)])
        self.assertEqual(result["positioningQualityProvenance"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_PROVEN)

    def test_g_unparseable_rtkflag_not_proven(self) -> None:
        result = evaluate_positioning_quality_v1([_frame("a.jpg", "not-a-flag")])
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_PROVEN)

    def test_h_mixed_50_and_16_not_supported(self) -> None:
        result = evaluate_positioning_quality_v1([_frame("a.jpg", "50"), _frame("b.jpg", "16", seq=2)])
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_SUPPORTED)
        self.assertEqual(result["fixedFrameCount"], 1)
        self.assertEqual(result["nonFixedFrameCount"], 1)

    def test_i_mixed_50_and_missing_not_proven(self) -> None:
        result = evaluate_positioning_quality_v1([_frame("a.jpg", "50"), _frame("b.jpg", None, seq=2)])
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_PROVEN)

    def test_j_mixed_50_16_and_missing_not_proven(self) -> None:
        result = evaluate_positioning_quality_v1(
            [_frame("a.jpg", "50"), _frame("b.jpg", "16", seq=2), _frame("c.jpg", None, seq=3)]
        )
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_PROVEN)
        self.assertEqual(result["selectedFrameCount"], 3)

    def test_k_conflict_human_review(self) -> None:
        result = evaluate_positioning_quality_v1([_frame("a.jpg", ["50", "16"])])
        self.assertEqual(result["positioningQualityProvenance"], "HUMAN_REVIEW_REQUIRED")
        self.assertEqual(result["positioningQualityReasonCode"], REASON_CONFLICT)
        self.assertFalse(result["positioningQualityExecutionAllowed"])

    def test_l_conflict_wins_over_missing_and_non_fixed(self) -> None:
        result = evaluate_positioning_quality_v1(
            [
                _frame("a.jpg", ["50", "16"]),
                _frame("b.jpg", None, seq=2),
                _frame("c.jpg", "16", seq=3),
            ]
        )
        self.assertEqual(result["positioningQualityReasonCode"], REASON_CONFLICT)
        self.assertEqual(result["conflictFrameCount"], 1)
        self.assertEqual(result["missingOrUnparseableFrameCount"], 1)
        self.assertEqual(result["nonFixedFrameCount"], 1)

    def test_m_input_order_permutation_same_aggregate(self) -> None:
        frames = [
            _frame("z.jpg", None, seq=3),
            _frame("a.jpg", "16", seq=1),
            _frame("m.jpg", "50", seq=2),
        ]
        left = evaluate_positioning_quality_v1(frames)
        right = evaluate_positioning_quality_v1(list(reversed(frames)))
        for key in (
            "positioningQualityReasonCode",
            "selectedFrameCount",
            "fixedFrameCount",
            "nonFixedFrameCount",
            "missingOrUnparseableFrameCount",
            "conflictFrameCount",
            "rtkFlagDistribution",
        ):
            self.assertEqual(left[key], right[key])

    def test_n_no_frame_filtering(self) -> None:
        frames = [_frame(f"{idx:04d}.jpg", "50", seq=idx) for idx in range(1, 8)]
        result = evaluate_positioning_quality_v1(frames)
        self.assertEqual(result["selectedFrameCount"], 7)
        self.assertEqual(len(result["frames"]), 7)

    def test_o_secondary_metadata_does_not_override_rtkflag(self) -> None:
        result = evaluate_positioning_quality_v1(
            [
                _frame(
                    "a.jpg",
                    "50",
                    GpsStatus="Normal",
                    SurveyingMode="0",
                    AltitudeType="GpsFusionAlt",
                )
            ]
        )
        self.assertEqual(result["positioningQualityReasonCode"], REASON_FIXED)
        self.assertTrue(result["positioningQualityExecutionAllowed"])

    def test_p_mrk_q_50_does_not_override_rtkflag_16(self) -> None:
        result = evaluate_positioning_quality_v1([_frame("a.jpg", "16", mrkQ="50")])
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_SUPPORTED)

    def test_q_mrk_q_16_does_not_override_rtkflag_50(self) -> None:
        result = evaluate_positioning_quality_v1([_frame("a.jpg", "50", mrkQ="16")])
        self.assertEqual(result["positioningQualityReasonCode"], REASON_FIXED)

    def test_empty_selected_set_is_not_proven(self) -> None:
        result = evaluate_positioning_quality_v1([])
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_PROVEN)
        self.assertFalse(result["positioningQualityExecutionAllowed"])
        self.assertEqual(result["selectedFrameCount"], 0)


class PositioningQualityCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_pq_col_"))
        self.incoming = self.tmp / "incoming" / "wall_test"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_collects_exactly_selected_paths(self) -> None:
        rels = (
            "flight/DJI_20260823122212_0001_V.JPG",
            "flight/DJI_20260823122214_0003_V.JPG",
        )
        write_jpeg(self.incoming / rels[0], xmp={"RtkFlag": "50", "GpsStatus": "RTK"})
        write_jpeg(self.incoming / rels[1], xmp={"RtkFlag": "16"})
        frames = collect_positioning_quality_frames(self.incoming, rels)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0]["rtkFlagOccurrences"], ["50"])
        self.assertEqual(frames[1]["rtkFlagOccurrences"], ["16"])
        result = evaluate_positioning_quality_v1(frames)
        self.assertEqual(result["selectedFrameCount"], 2)
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_SUPPORTED)

    def test_collect_duplicate_rtkflag_is_conflict(self) -> None:
        rel = "flight/DJI_20260823122212_0001_V.JPG"
        write_jpeg(self.incoming / rel, xmp={"RtkFlag": "50"})
        data = (self.incoming / rel).read_bytes()
        replaced = data.replace(b'drone-dji:RtkFlag="50"', b'drone-dji:RtkFlag="50" drone-dji:RtkFlag="16"', 1)
        (self.incoming / rel).write_bytes(replaced)
        frames = collect_positioning_quality_frames(self.incoming, (rel,))
        self.assertEqual(frames[0]["rtkFlagOccurrences"], ["50", "16"])
        result = evaluate_positioning_quality_v1(frames)
        self.assertEqual(result["positioningQualityReasonCode"], REASON_CONFLICT)


class PositioningQualityPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_pq_pipe_"))
        self.wall_id = "wall_test_pq_gate"
        incoming = self.tmp / "incoming" / self.wall_id
        meta = incoming / "export" / "terra_ply" / "metadata.xml"
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<ModelMetadata version=\"1\">\n"
            "<SRS>EPSG:32650</SRS>\n"
            "<SRSOrigin>100.0,200.0,10.0</SRSOrigin>\n"
            "</ModelMetadata>\n",
            encoding="utf-8",
        )
        self.dest = self.tmp / "metric_registration"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sources(self, frames: tuple[dict, ...]) -> Stage2SelectedSources:
        return Stage2SelectedSources(
            wall_id=self.wall_id,
            image_relative_paths=tuple(item["imageRelativePath"] for item in frames),
            image_dir_relative="flight",
            mrk_relative_path="flight/x.MRK",
            metadata_xml_relative_path=META,
            srs="EPSG:32650",
            srs_origin=ORIGIN,
            ply_relative_path=None,
            association_method="test",
            association_rule="test",
            height_provenance_evidence=_approved_height(),
            positioning_quality_frames=frames,
        )

    def _assert_not_sim3(self, payload: dict, corr, umeyama_fn, ransac) -> None:
        corr.assert_not_called()
        umeyama_fn.assert_not_called()
        ransac.assert_not_called()
        self.assertNotIn("scale", payload)
        self.assertFalse(payload["positioningQualityExecutionAllowed"])
        self.assertTrue(payload["productionBuildStage2Enabled"])
        self.assertTrue(payload["genericStage2Pass"])

    def test_not_supported_stops_before_sim3(self) -> None:
        sources = self._sources((_frame("flight/DJI_20260823122200_0001_V.JPG", "16"),))
        with patch("offline.metric_registration.pipeline.ransac_umeyama") as ransac, patch(
            "offline.metric_registration.pipeline.umeyama"
        ) as umeyama_fn, patch(
            "offline.metric_registration.pipeline.build_correspondences"
        ) as corr:
            corr.side_effect = RuntimeError("REACHED_CORRESPONDENCES")
            ransac.side_effect = AssertionError("SIM3_CALLED")
            umeyama_fn.side_effect = AssertionError("SIM3_CALLED")
            payload = register(self.wall_id, self.tmp, sources=sources, dest=self.dest)
        self._assert_not_sim3(payload, corr, umeyama_fn, ransac)
        self.assertEqual(payload["reasonCode"], REASON_NOT_SUPPORTED)

    def test_not_proven_stops_before_sim3(self) -> None:
        sources = self._sources((_frame("flight/DJI_20260823122200_0001_V.JPG", None),))
        with patch("offline.metric_registration.pipeline.ransac_umeyama") as ransac, patch(
            "offline.metric_registration.pipeline.umeyama"
        ) as umeyama_fn, patch(
            "offline.metric_registration.pipeline.build_correspondences"
        ) as corr:
            payload = register(self.wall_id, self.tmp, sources=sources, dest=self.dest)
        self._assert_not_sim3(payload, corr, umeyama_fn, ransac)
        self.assertEqual(payload["reasonCode"], REASON_NOT_PROVEN)

    def test_conflict_stops_before_sim3(self) -> None:
        sources = self._sources((_frame("flight/DJI_20260823122200_0001_V.JPG", ["50", "16"]),))
        with patch("offline.metric_registration.pipeline.ransac_umeyama") as ransac, patch(
            "offline.metric_registration.pipeline.umeyama"
        ) as umeyama_fn, patch(
            "offline.metric_registration.pipeline.build_correspondences"
        ) as corr:
            payload = register(self.wall_id, self.tmp, sources=sources, dest=self.dest)
        self._assert_not_sim3(payload, corr, umeyama_fn, ransac)
        self.assertEqual(payload["reasonCode"], REASON_CONFLICT)
        self.assertEqual(payload["gateResult"], "HUMAN_REVIEW_REQUIRED")

    def test_pass_may_continue_past_positioning_quality_gate(self) -> None:
        sources = self._sources((_frame("flight/DJI_20260823122200_0001_V.JPG", "50"),))
        gate = evaluate_positioning_quality_from_sources(self.tmp / "incoming" / self.wall_id, sources)
        self.assertTrue(gate["positioningQualityExecutionAllowed"])
        self.assertEqual(gate["positioningQualityReasonCode"], REASON_FIXED)
        try:
            import pycolmap
        except ImportError:
            return
        fake = MagicMock()
        fake.return_value.num_reg_images.return_value = 0
        fake.return_value.num_points3D.return_value = 0
        with patch.object(pycolmap, "Reconstruction", fake), patch(
            "offline.metric_registration.pipeline.build_correspondences"
        ) as corr, patch("offline.metric_registration.pipeline.ransac_umeyama") as ransac, patch(
            "offline.metric_registration.pipeline.evaluate_colmap_source_identity"
        ) as ident:
            ident.return_value = {
                "colmapSourceIdentityExecutionAllowed": True,
                "colmapSourceIdentityProvenance": "AUTO_PASS",
                "colmapSourceIdentityReasonCode": "COLMAP_SOURCE_IDENTITY_PROVEN",
                "resolvedModelPath": str(self.tmp / "colmap_model"),
                "problems": [],
            }
            corr.side_effect = RuntimeError("REACHED_CORRESPONDENCES")
            ransac.side_effect = AssertionError("SIM3_CALLED")
            payload = register(self.wall_id, self.tmp, sources=sources, dest=self.dest)
        ransac.assert_not_called()
        self.assertTrue(any("REACHED_CORRESPONDENCES" in str(item) for item in payload.get("errors") or []))


class PositioningQualityRealRegressionTests(unittest.TestCase):
    def test_jinshidong_blocks_not_proven_before_sim3(self) -> None:
        incoming = ROOT / "incoming" / "wall_jinshidong_01"
        if not incoming.is_dir():
            self.skipTest("incoming/wall_jinshidong_01 not present")
        artifact = select_stage2_inputs("wall_jinshidong_01", ROOT)
        sources = sources_from_selection(artifact)
        self.assertIsNotNone(sources)
        result = evaluate_positioning_quality_from_sources(incoming, sources)
        if (
            result["selectedFrameCount"] != 179
            or result["fixedFrameCount"] != 0
            or result["nonFixedFrameCount"] != 152
            or result["missingOrUnparseableFrameCount"] != 27
        ):
            self.fail(
                "REAL_REGRESSION_EVIDENCE_CONTRADICTION "
                f"selected={result['selectedFrameCount']} "
                f"fixed={result['fixedFrameCount']} "
                f"nonFixed={result['nonFixedFrameCount']} "
                f"missing={result['missingOrUnparseableFrameCount']}"
            )
        self.assertEqual(result["positioningQualityReasonCode"], REASON_NOT_PROVEN)
        self.assertFalse(result["positioningQualityExecutionAllowed"])
        dest = Path(tempfile.mkdtemp(prefix="rv_pq_js_")) / "metric_registration"
        try:
            with patch("offline.metric_registration.pipeline.ransac_umeyama") as ransac, patch(
                "offline.metric_registration.pipeline.umeyama"
            ) as umeyama_fn, patch(
                "offline.metric_registration.pipeline.build_correspondences"
            ) as corr:
                corr.side_effect = RuntimeError("REACHED_CORRESPONDENCES")
                payload = register("wall_jinshidong_01", ROOT, sources=sources, dest=dest)
            corr.assert_not_called()
            umeyama_fn.assert_not_called()
            ransac.assert_not_called()
            self.assertEqual(payload["reasonCode"], REASON_NOT_PROVEN)
            self.assertFalse(payload["positioningQualityExecutionAllowed"])
            self.assertNotIn("scale", payload)
            self.assertTrue(payload["productionBuildStage2Enabled"])
        finally:
            shutil.rmtree(dest.parent, ignore_errors=True)

    def test_jiulongfeng_all_fixed_auto_pass(self) -> None:
        incoming = ROOT / "incoming" / "wall_jiulongfeng_01"
        if not incoming.is_dir():
            self.skipTest("incoming/wall_jiulongfeng_01 not present")
        artifact = select_stage2_inputs("wall_jiulongfeng_01", ROOT)
        export = (artifact.get("selectedCapture") or {}).get("memberRelativePaths") or ()
        self.assertTrue(all(str(rel).startswith("DJI_202608231218_006_九龙峰/") for rel in export))
        sources = sources_from_selection(artifact)
        self.assertIsNotNone(sources)
        result = evaluate_positioning_quality_from_sources(incoming, sources)
        if (
            result["selectedFrameCount"] != 47
            or result["fixedFrameCount"] != 47
            or result["missingOrUnparseableFrameCount"] != 0
            or result["nonFixedFrameCount"] != 0
            or result["conflictFrameCount"] != 0
        ):
            self.fail(
                "REAL_REGRESSION_EVIDENCE_CONTRADICTION "
                f"selected={result['selectedFrameCount']} "
                f"fixed={result['fixedFrameCount']} "
                f"nonFixed={result['nonFixedFrameCount']} "
                f"missing={result['missingOrUnparseableFrameCount']} "
                f"conflict={result['conflictFrameCount']}"
            )
        self.assertEqual(result["positioningQualityProvenance"], "AUTO_PASS")
        self.assertEqual(result["positioningQualityReasonCode"], REASON_FIXED)
        self.assertTrue(result["positioningQualityExecutionAllowed"])


if __name__ == "__main__":
    unittest.main()
