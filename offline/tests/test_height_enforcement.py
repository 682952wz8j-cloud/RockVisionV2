from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.metric_registration.height_datum import (
    EVIDENCE_NOT_AVAILABLE as HEIGHT_EVIDENCE_NOT_AVAILABLE,
    FIELD_NOT_PRESENT as HEIGHT_FIELD_NOT_PRESENT,
    FIELD_PRESENT_EMPTY as HEIGHT_FIELD_PRESENT_EMPTY,
    FIELD_CONFLICT as HEIGHT_FIELD_CONFLICT,
    FIELD_PRESENT_POPULATED as HEIGHT_FIELD_PRESENT_POPULATED,
    HEIGHT_VERTICAL_DATUM_ENFORCEMENT_IMPLEMENTED,
    MULTIPLE_OVERRIDE_DESCRIPTOR_CORRECTION_IMPLEMENTED,
    VERTICAL_OVERRIDE_CONFLICT_PRECEDENCE_CORRECTION_IMPLEMENTED,
    VERTICAL_OVERRIDE_ABSENCE_CORRECTION_IMPLEMENTED,
    REASON_ELLIPSOID_CONFLICT,
    REASON_ELLIPSOID_NOT_PROVEN,
    REASON_GEOID_NOT_PROVEN,
    REASON_GEOID_UNSUPPORTED,
    REASON_HEIGHT_APPROVED,
    REASON_INVALID_ORIGIN,
    REASON_MRK_ELLH_NOT_PROVEN,
    REASON_MRK_SEMANTIC_CONTRADICTION,
    REASON_NON_WGS84_UNSUPPORTED,
    REASON_OVERRIDE_CONFLICT,
    REASON_OVERRIDE_NOT_PROVEN,
    REASON_OVERRIDE_UNSUPPORTED,
    REASON_TERRA_VERTICAL_NOT_PROVEN,
    REASON_TERRA_VERTICAL_UNSUPPORTED,
    evaluate_generic_height_from_sources,
    evaluate_generic_height_provenance,
    height_evidence_from_rule_c_payload,
    vertical_override_state_from_terra_evidence,
)
from offline.metric_registration.pipeline import register
from offline.stage2_selection.ellipsoid import (
    EVIDENCE_NOT_AVAILABLE,
    FIELD_CONFLICT,
    FIELD_NOT_PRESENT,
    FIELD_PRESENT_EMPTY,
    FIELD_PRESENT_POPULATED,
    collect_terra_vertical_evidence,
)
from offline.stage2_selection.select import select_stage2_inputs
from offline.stage2_selection.sources import Stage2SelectedSources, sources_from_selection

ORIGIN = [100.0, 200.0, 10.0]
META = "export/terra_ply/metadata.xml"


def _approved(**overrides) -> dict:
    evidence = {
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
    evidence.update(overrides)
    return evidence


def _assert_blocked(test: unittest.TestCase, result: dict, *, provenance: str, reason: str) -> None:
    test.assertEqual(result["heightVerticalDatumProvenance"], provenance)
    test.assertEqual(result["reasonCode"], reason)
    test.assertFalse(result["heightGateExecutionAllowed"])
    test.assertTrue(HEIGHT_VERTICAL_DATUM_ENFORCEMENT_IMPLEMENTED)


class HeightEnforcementUnitTests(unittest.TestCase):
    def test_a_approved_rule_c_default_wgs84(self) -> None:
        result = evaluate_generic_height_provenance(_approved())
        self.assertEqual(result["heightVerticalDatumProvenance"], "AUTO_PASS")
        self.assertTrue(result["heightGateExecutionAllowed"])
        self.assertEqual(result["reasonCode"], REASON_HEIGHT_APPROVED)
        self.assertEqual(result["heightDatumUsed"], "ELLIPSOIDAL")
        self.assertEqual(result["referenceEllipsoid"], "WGS84")
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC")
        self.assertEqual(result["terraVerticalMode"], "DEFAULT")
        self.assertEqual(result["geoidConversionConfigured"], "NO")
        self.assertEqual(result["verticalOverrideConfigured"], "NO")
        self.assertEqual(result["wallLocalZOperation"], "ELLH_MINUS_SRSORIGIN_Z")
        self.assertTrue(result["sameVerticalFrame"])
        self.assertFalse(result["mixedDatumDetected"])
        self.assertTrue(result["noGeoidOffsetApplied"])
        self.assertFalse(result["productionBuildStage2Enabled"])
        self.assertFalse(result["genericStage2Pass"])

    def test_b_proven_wgs84(self) -> None:
        result = evaluate_generic_height_provenance(
            _approved(
                referenceEllipsoidProvenanceStatus="PROVEN_WGS84",
                specDefaultInvoked=False,
            )
        )
        self.assertEqual(result["heightVerticalDatumProvenance"], "AUTO_PASS")
        self.assertTrue(result["heightGateExecutionAllowed"])
        self.assertEqual(result["referenceEllipsoidProvenanceStatus"], "PROVEN_WGS84")

    def test_c_reference_unknown(self) -> None:
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(_approved(referenceEllipsoidProvenanceStatus="UNKNOWN")),
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_ELLIPSOID_NOT_PROVEN,
        )

    def test_d_proven_non_wgs84(self) -> None:
        result = evaluate_generic_height_provenance(
            _approved(
                referenceEllipsoid="CGCS2000",
                referenceEllipsoidProvenanceStatus="PROVEN_NON_WGS84",
            )
        )
        _assert_blocked(
            self,
            result,
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_NON_WGS84_UNSUPPORTED,
        )

    def test_e_conflicting_evidence(self) -> None:
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(
                _approved(referenceEllipsoidProvenanceStatus="CONFLICTING_EVIDENCE")
            ),
            provenance="HUMAN_REVIEW_REQUIRED",
            reason=REASON_ELLIPSOID_CONFLICT,
        )
        self.assertFalse(
            evaluate_generic_height_provenance(
                _approved(referenceEllipsoidProvenanceStatus="CONFLICTING_EVIDENCE")
            )["mixedDatumDetected"]
        )

    def test_f_mrk_ellh_missing(self) -> None:
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(_approved(mrkEllhValid=False)),
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_MRK_ELLH_NOT_PROVEN,
        )

    def test_g_mrk_explicit_non_ellipsoidal(self) -> None:
        result = evaluate_generic_height_provenance(
            _approved(heightObservationSemantic="ORTHOMETRIC")
        )
        _assert_blocked(
            self,
            result,
            provenance="AUTO_FAIL",
            reason=REASON_MRK_SEMANTIC_CONTRADICTION,
        )
        self.assertTrue(result["mixedDatumDetected"])

    def test_h_terra_vertical_unknown(self) -> None:
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(_approved(terraVerticalMode="UNKNOWN")),
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_TERRA_VERTICAL_NOT_PROVEN,
        )

    def test_i_terra_unsupported_vertical(self) -> None:
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(_approved(terraVerticalMode="EGM96")),
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_TERRA_VERTICAL_UNSUPPORTED,
        )

    def test_j_geoid_yes(self) -> None:
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(_approved(geoidConversionConfigured="YES")),
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_GEOID_UNSUPPORTED,
        )

    def test_k_geoid_unknown(self) -> None:
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(_approved(geoidConversionConfigured="UNKNOWN")),
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_GEOID_NOT_PROVEN,
        )

    def test_l_vertical_override_populated(self) -> None:
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(_approved(verticalOverrideConfigured="YES")),
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_OVERRIDE_UNSUPPORTED,
        )

    def test_m_vertical_override_unknown(self) -> None:
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(_approved(verticalOverrideConfigured="UNKNOWN")),
            provenance="DEVELOPMENT_GATE_REVIEW_REQUIRED",
            reason=REASON_OVERRIDE_NOT_PROVEN,
        )

    def test_n_invalid_srsorigin_length(self) -> None:
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(_approved(usedSrsOrigin=[1.0, 2.0], srsOriginProvenanceOk=True)),
            provenance="AUTO_FAIL",
            reason=REASON_INVALID_ORIGIN,
        )

    def test_o_nan_inf_srsorigin(self) -> None:
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(_approved(usedSrsOrigin=[1.0, 2.0, float("nan")])),
            provenance="AUTO_FAIL",
            reason=REASON_INVALID_ORIGIN,
        )
        _assert_blocked(
            self,
            evaluate_generic_height_provenance(_approved(usedSrsOrigin=[1.0, 2.0, float("inf")])),
            provenance="AUTO_FAIL",
            reason=REASON_INVALID_ORIGIN,
        )

    def test_p_wall_id_cannot_change_result(self) -> None:
        left = evaluate_generic_height_provenance(_approved(wallId="wall_jinshidong_01"))
        right = evaluate_generic_height_provenance(_approved(wallId="wall_other"))
        self.assertEqual(left["heightVerticalDatumProvenance"], right["heightVerticalDatumProvenance"])
        self.assertEqual(left["reasonCode"], right["reasonCode"])
        self.assertEqual(left["heightGateExecutionAllowed"], right["heightGateExecutionAllowed"])

    def test_q_numeric_closeness_cannot_change_result(self) -> None:
        unknown = _approved(referenceEllipsoidProvenanceStatus="UNKNOWN")
        close = evaluate_generic_height_provenance({**unknown, "numericCloseness": 0.0})
        far = evaluate_generic_height_provenance({**unknown, "numericCloseness": 999.0})
        self.assertEqual(close["reasonCode"], REASON_ELLIPSOID_NOT_PROVEN)
        self.assertEqual(far["reasonCode"], REASON_ELLIPSOID_NOT_PROVEN)
        self.assertFalse(close["heightGateExecutionAllowed"])

    def test_r_sim3_metrics_cannot_change_result(self) -> None:
        unknown = _approved(referenceEllipsoidProvenanceStatus="UNKNOWN")
        good = evaluate_generic_height_provenance({**unknown, "sim3Metrics": {"median": 0.01, "scale": 3.19}})
        bad = evaluate_generic_height_provenance({**unknown, "sim3Metrics": {"median": 50.0}})
        self.assertEqual(good["reasonCode"], bad["reasonCode"])
        self.assertFalse(good["heightGateExecutionAllowed"])

    def test_override_state_requires_explicit_field_state(self) -> None:
        self.assertEqual(vertical_override_state_from_terra_evidence([]), "UNKNOWN")
        self.assertEqual(
            vertical_override_state_from_terra_evidence(
                [{"field": "override_vertical_cs", "rawValue": None}]
            ),
            "UNKNOWN",
        )
        self.assertEqual(
            vertical_override_state_from_terra_evidence(
                [{"field": "override_vertical_cs", "rawValue": "", "fieldState": FIELD_PRESENT_EMPTY}]
            ),
            "NO",
        )
        self.assertEqual(
            vertical_override_state_from_terra_evidence(
                [{"field": "override_vertical_cs", "rawValue": "EPSG:5703", "fieldState": FIELD_PRESENT_POPULATED}]
            ),
            "YES",
        )


class HeightEnforcementPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_height_pipe_"))
        self.wall_id = "wall_test_height_gate"
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

    def _sources(self, evidence: dict) -> Stage2SelectedSources:
        return Stage2SelectedSources(
            wall_id=self.wall_id,
            image_relative_paths=("flight/DJI_20260823122200_0001_V.JPG",),
            image_dir_relative="flight",
            mrk_relative_path="flight/x.MRK",
            metadata_xml_relative_path=META,
            srs="EPSG:32650",
            srs_origin=(100.0, 200.0, 10.0),
            ply_relative_path=None,
            association_method="test",
            association_rule="test",
            height_provenance_evidence=evidence,
            positioning_quality_frames=(
                {
                    "imageRelativePath": "flight/DJI_20260823122200_0001_V.JPG",
                    "sequence": 1,
                    "rtkFlagOccurrences": ["50"],
                },
            ),
        )

    def test_unknown_ellipsoid_stops_before_sim3(self) -> None:
        sources = self._sources(_approved(referenceEllipsoidProvenanceStatus="UNKNOWN", srsOriginProvenanceOk=True))
        with patch("offline.metric_registration.pipeline.ransac_umeyama") as ransac, patch(
            "offline.metric_registration.pipeline.umeyama"
        ) as umeyama_fn, patch(
            "offline.metric_registration.pipeline.build_correspondences"
        ) as corr:
            corr.side_effect = RuntimeError("REACHED_CORRESPONDENCES")
            ransac.side_effect = AssertionError("SIM3_CALLED")
            umeyama_fn.side_effect = AssertionError("SIM3_CALLED")
            payload = register(self.wall_id, self.tmp, sources=sources, dest=self.dest)

        ransac.assert_not_called()
        umeyama_fn.assert_not_called()
        corr.assert_not_called()
        self.assertFalse(payload["heightGateExecutionAllowed"])
        self.assertEqual(payload["reasonCode"], REASON_ELLIPSOID_NOT_PROVEN)
        self.assertEqual(payload["heightVerticalDatumProvenance"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertEqual(payload["validationStatus"], "NOT VALIDATED")
        self.assertNotIn("scale", payload)

    def test_conflicting_override_descriptors_stop_before_sim3(self) -> None:
        sources = self._sources(
            _approved(
                verticalOverrideConfigured="UNKNOWN",
                verticalOverrideFieldState=FIELD_CONFLICT,
                srsOriginProvenanceOk=True,
            )
        )
        with patch("offline.metric_registration.pipeline.ransac_umeyama") as ransac, patch(
            "offline.metric_registration.pipeline.umeyama"
        ) as umeyama_fn, patch(
            "offline.metric_registration.pipeline.build_correspondences"
        ) as corr:
            corr.side_effect = RuntimeError("REACHED_CORRESPONDENCES")
            ransac.side_effect = AssertionError("SIM3_CALLED")
            umeyama_fn.side_effect = AssertionError("SIM3_CALLED")
            payload = register(self.wall_id, self.tmp, sources=sources, dest=self.dest)

        ransac.assert_not_called()
        umeyama_fn.assert_not_called()
        corr.assert_not_called()
        self.assertFalse(payload["heightGateExecutionAllowed"])
        self.assertEqual(payload["reasonCode"], REASON_OVERRIDE_CONFLICT)
        self.assertEqual(payload["heightVerticalDatumProvenance"], "HUMAN_REVIEW_REQUIRED")
        self.assertNotIn("scale", payload)

    def test_approved_evidence_may_continue_past_height_gate(self) -> None:
        sources = self._sources(_approved(srsOriginProvenanceOk=True))
        gate = evaluate_generic_height_from_sources(self.tmp / "incoming" / self.wall_id, sources)
        self.assertTrue(gate["heightGateExecutionAllowed"])
        self.assertEqual(gate["reasonCode"], REASON_HEIGHT_APPROVED)
        try:
            import pycolmap
        except ImportError:
            return
        fake = MagicMock()
        fake.return_value.num_reg_images.return_value = 0
        fake.return_value.num_points3D.return_value = 0
        with patch.object(pycolmap, "Reconstruction", fake), patch(
            "offline.metric_registration.pipeline.build_correspondences"
        ) as corr, patch("offline.metric_registration.pipeline.ransac_umeyama") as ransac:
            corr.side_effect = RuntimeError("REACHED_CORRESPONDENCES")
            ransac.side_effect = AssertionError("SIM3_CALLED")
            payload = register(self.wall_id, self.tmp, sources=sources, dest=self.dest)
        ransac.assert_not_called()
        self.assertTrue(any("REACHED_CORRESPONDENCES" in str(item) for item in payload.get("errors") or []))


class JinshidongHeightEnforcementTests(unittest.TestCase):
    def test_real_jinshidong_expected_auto_pass(self) -> None:
        incoming = ROOT / "incoming" / "wall_jinshidong_01"
        if not incoming.is_dir():
            self.skipTest("incoming/wall_jinshidong_01 not present")
        artifact = select_stage2_inputs("wall_jinshidong_01", ROOT)
        sources = sources_from_selection(artifact)
        self.assertIsNotNone(sources)
        result = evaluate_generic_height_from_sources(incoming, sources)
        self.assertEqual(result["referenceEllipsoid"], "WGS84")
        self.assertEqual(
            result["referenceEllipsoidProvenanceStatus"],
            "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC",
        )
        self.assertTrue(result["mrkEllhValid"])
        self.assertEqual(result["terraVerticalMode"], "DEFAULT")
        self.assertEqual(result["geoidConversionConfigured"], "NO")
        self.assertEqual(result["verticalOverrideConfigured"], "NO")
        self.assertEqual(result["heightVerticalDatumProvenance"], "AUTO_PASS")
        self.assertTrue(result["heightGateExecutionAllowed"])
        self.assertEqual(result["reasonCode"], REASON_HEIGHT_APPROVED)
        self.assertTrue(HEIGHT_VERTICAL_DATUM_ENFORCEMENT_IMPLEMENTED)
        override = next(
            item
            for item in (artifact["gnssReferenceEllipsoidProvenance"]["terraVerticalEvidence"] or [])
            if item.get("field") == "override_vertical_cs"
        )
        self.assertEqual(override["fieldState"], FIELD_PRESENT_EMPTY)
        self.assertEqual(override["rawValue"], "")

    def test_rule_c_payload_is_consumed_not_reimplemented(self) -> None:
        projected = height_evidence_from_rule_c_payload(
            {
                "referenceEllipsoid": "WGS84",
                "referenceEllipsoidProvenanceStatus": "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC",
                "specDefaultInvoked": True,
                "mrkEllh": {"valid": True, "validRecordCount": 2},
                "heightObservationSemantic": "GNSS_GEODETIC_ELLIPSOIDAL_HEIGHT",
                "terraVerticalMode": "DEFAULT",
                "geoidConversionConfigured": "NO",
                "terraVerticalEvidence": [
                    {
                        "field": "override_vertical_cs",
                        "rawValue": "",
                        "fieldState": FIELD_PRESENT_EMPTY,
                    }
                ],
                "policy": "RULE_C_SPEC_GOVERNED_DEFAULT",
            },
            selected_srs_origin=ORIGIN,
            selected_metadata_relative_path=META,
            terra_export_root_relative="export",
        )
        self.assertTrue(projected["ruleCConsumed"])
        self.assertEqual(projected["verticalOverrideConfigured"], "NO")
        self.assertEqual(
            evaluate_generic_height_provenance({**projected, "usedSrsOrigin": ORIGIN, "usedMetadataRelativePath": META})[
                "reasonCode"
            ],
            REASON_HEIGHT_APPROVED,
        )


def _override_rows(collected: dict) -> list[dict]:
    return [item for item in collected.get("evidence") or [] if item.get("field") == "override_vertical_cs"]


class VerticalOverrideAbsenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_override_abs_"))
        self.incoming = self.tmp / "incoming" / "wall_test"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_sdk(self, export: Path, body: str) -> None:
        path = export / "SDK_Log.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def test_a_inspected_field_absent_is_not_present(self) -> None:
        export = self.incoming / "export0"
        self._write_sdk(export, '[I]Output geo descriptor: {"cs_type":"GEO_CS","geo_cs":"EPSG:32650"}\n')
        collected = collect_terra_vertical_evidence(self.incoming, "export0")
        rows = _override_rows(collected)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fieldState"], FIELD_NOT_PRESENT)
        self.assertIsNone(rows[0]["rawValue"])
        self.assertEqual(rows[0]["overrideVerticalCsOccurrenceCount"], 0)
        self.assertEqual(rows[0]["rawValues"], [])
        self.assertEqual(rows[0]["path"], "export0/SDK_Log.txt")
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "NO")
        result = evaluate_generic_height_provenance(
            _approved(verticalOverrideConfigured=vertical_override_state_from_terra_evidence(collected["evidence"]))
        )
        self.assertEqual(result["verticalOverrideConfigured"], "NO")
        self.assertTrue(result["heightGateExecutionAllowed"])

    def test_b_inspected_field_present_empty(self) -> None:
        export = self.incoming / "export0"
        self._write_sdk(
            export,
            '[I]Output geo descriptor: {"cs_type":"GEO_CS","override_vertical_cs":""}\n',
        )
        collected = collect_terra_vertical_evidence(self.incoming, "export0")
        rows = _override_rows(collected)
        self.assertEqual(rows[0]["fieldState"], FIELD_PRESENT_EMPTY)
        self.assertEqual(rows[0]["rawValue"], "")
        self.assertEqual(rows[0]["overrideVerticalCsOccurrenceCount"], 1)
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "NO")

    def test_c_multiple_all_empty_is_present_empty(self) -> None:
        export = self.incoming / "export0"
        self._write_sdk(
            export,
            '[I]{"override_vertical_cs":""}\n[I]{"override_vertical_cs":"   "}\n[I]{"override_vertical_cs":""}\n',
        )
        collected = collect_terra_vertical_evidence(self.incoming, "export0")
        rows = _override_rows(collected)
        self.assertEqual(rows[0]["fieldState"], FIELD_PRESENT_EMPTY)
        self.assertEqual(rows[0]["overrideVerticalCsOccurrenceCount"], 3)
        self.assertEqual(rows[0]["rawValues"], ["", "   ", ""])
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "NO")
        result = evaluate_generic_height_provenance(
            _approved(verticalOverrideConfigured="NO", verticalOverrideFieldState=FIELD_PRESENT_EMPTY)
        )
        self.assertTrue(result["heightGateExecutionAllowed"])

    def test_b_whitespace_only_is_present_empty(self) -> None:
        export = self.incoming / "export0"
        self._write_sdk(
            export,
            '[I]Output geo descriptor: {"override_vertical_cs":"   "}\n',
        )
        collected = collect_terra_vertical_evidence(self.incoming, "export0")
        rows = _override_rows(collected)
        self.assertEqual(rows[0]["fieldState"], FIELD_PRESENT_EMPTY)
        self.assertEqual(rows[0]["rawValue"], "   ")
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "NO")

    def test_c_inspected_field_populated_blocks_gate(self) -> None:
        export = self.incoming / "export0"
        self._write_sdk(
            export,
            '[I]Output geo descriptor: {"override_vertical_cs":"EGM96"}\n',
        )
        collected = collect_terra_vertical_evidence(self.incoming, "export0")
        rows = _override_rows(collected)
        self.assertEqual(rows[0]["fieldState"], FIELD_PRESENT_POPULATED)
        self.assertEqual(rows[0]["rawValue"], "EGM96")
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "YES")
        result = evaluate_generic_height_provenance(_approved(verticalOverrideConfigured="YES"))
        self.assertEqual(result["heightVerticalDatumProvenance"], "DEVELOPMENT_GATE_REVIEW_REQUIRED")
        self.assertEqual(result["reasonCode"], REASON_OVERRIDE_UNSUPPORTED)
        self.assertFalse(result["heightGateExecutionAllowed"])

    def test_e_multiple_identical_populated_blocks_gate(self) -> None:
        export = self.incoming / "export0"
        self._write_sdk(
            export,
            '[I]{"override_vertical_cs":"EGM96"}\n[I]{"override_vertical_cs":"EGM96"}\n',
        )
        collected = collect_terra_vertical_evidence(self.incoming, "export0")
        rows = _override_rows(collected)
        self.assertEqual(rows[0]["fieldState"], FIELD_PRESENT_POPULATED)
        self.assertEqual(rows[0]["overrideVerticalCsOccurrenceCount"], 2)
        self.assertEqual(rows[0]["rawValues"], ["EGM96", "EGM96"])
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "YES")
        result = evaluate_generic_height_provenance(_approved(verticalOverrideConfigured="YES"))
        self.assertEqual(result["reasonCode"], REASON_OVERRIDE_UNSUPPORTED)
        self.assertFalse(result["heightGateExecutionAllowed"])

    def test_f_empty_plus_populated_is_conflict(self) -> None:
        export = self.incoming / "export0"
        self._write_sdk(
            export,
            '[I]{"override_vertical_cs":""}\n[I]{"override_vertical_cs":"EGM96"}\n',
        )
        collected = collect_terra_vertical_evidence(self.incoming, "export0")
        rows = _override_rows(collected)
        self.assertEqual(rows[0]["fieldState"], FIELD_CONFLICT)
        self.assertEqual(rows[0]["overrideVerticalCsOccurrenceCount"], 2)
        self.assertEqual(rows[0]["rawValues"], ["", "EGM96"])
        self.assertNotEqual(rows[0]["rawValue"], "")
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "UNKNOWN")
        projected = height_evidence_from_rule_c_payload(
            {"terraVerticalEvidence": collected["evidence"]},
            selected_srs_origin=ORIGIN,
            selected_metadata_relative_path=META,
            terra_export_root_relative="export0",
        )
        result = evaluate_generic_height_provenance(
            _approved(
                verticalOverrideConfigured=projected["verticalOverrideConfigured"],
                verticalOverrideFieldState=projected["verticalOverrideFieldState"],
            )
        )
        self.assertEqual(projected["verticalOverrideFieldState"], FIELD_CONFLICT)
        self.assertEqual(result["reasonCode"], REASON_OVERRIDE_CONFLICT)
        self.assertEqual(result["heightVerticalDatumProvenance"], "HUMAN_REVIEW_REQUIRED")
        self.assertFalse(result["heightGateExecutionAllowed"])

    def test_g_different_populated_values_are_conflict(self) -> None:
        export = self.incoming / "export0"
        self._write_sdk(
            export,
            '[I]{"override_vertical_cs":"EGM96"}\n[I]{"override_vertical_cs":"EPSG:5703"}\n',
        )
        collected = collect_terra_vertical_evidence(self.incoming, "export0")
        rows = _override_rows(collected)
        self.assertEqual(rows[0]["fieldState"], FIELD_CONFLICT)
        self.assertEqual(rows[0]["rawValues"], ["EGM96", "EPSG:5703"])
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "UNKNOWN")
        result = evaluate_generic_height_provenance(
            _approved(verticalOverrideConfigured="UNKNOWN", verticalOverrideFieldState=FIELD_CONFLICT)
        )
        self.assertEqual(result["reasonCode"], REASON_OVERRIDE_CONFLICT)
        self.assertFalse(result["heightGateExecutionAllowed"])

    def test_d_config_unavailable_is_not_available(self) -> None:
        collected = collect_terra_vertical_evidence(self.incoming, "missing_export")
        rows = _override_rows(collected)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fieldState"], EVIDENCE_NOT_AVAILABLE)
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "UNKNOWN")
        result = evaluate_generic_height_provenance(_approved(verticalOverrideConfigured="UNKNOWN"))
        self.assertEqual(result["reasonCode"], REASON_OVERRIDE_NOT_PROVEN)
        self.assertFalse(result["heightGateExecutionAllowed"])

    def test_i_read_failure_is_not_available(self) -> None:
        export = self.incoming / "export0"
        self._write_sdk(export, '{"override_vertical_cs":""}\n')
        sdk = export / "SDK_Log.txt"
        original = Path.read_text

        def _read(self, *args, **kwargs):
            if self == sdk:
                raise OSError("unreadable")
            return original(self, *args, **kwargs)

        with patch.object(Path, "read_text", _read):
            collected = collect_terra_vertical_evidence(self.incoming, "export0")
        rows = _override_rows(collected)
        self.assertEqual(rows[0]["fieldState"], EVIDENCE_NOT_AVAILABLE)
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "UNKNOWN")

    def test_d_no_export_root_is_not_available(self) -> None:
        collected = collect_terra_vertical_evidence(self.incoming, None)
        rows = _override_rows(collected)
        self.assertEqual(rows[0]["fieldState"], EVIDENCE_NOT_AVAILABLE)
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "UNKNOWN")

    def test_e_empty_terra_evidence_is_unknown(self) -> None:
        self.assertEqual(vertical_override_state_from_terra_evidence([]), "UNKNOWN")
        result = evaluate_generic_height_provenance(_approved(verticalOverrideConfigured="UNKNOWN"))
        self.assertEqual(result["reasonCode"], REASON_OVERRIDE_NOT_PROVEN)
        self.assertFalse(result["heightGateExecutionAllowed"])

    def test_f_unrecognized_field_state_is_unknown(self) -> None:
        self.assertEqual(
            vertical_override_state_from_terra_evidence(
                [{"field": "override_vertical_cs", "fieldState": "MAYBE_ABSENT", "rawValue": None}]
            ),
            "UNKNOWN",
        )

    def test_i_conflicting_rows_do_not_auto_pass(self) -> None:
        mapped = vertical_override_state_from_terra_evidence(
            [
                {"field": "override_vertical_cs", "fieldState": FIELD_PRESENT_POPULATED, "rawValue": "EGM96"},
                {"field": "override_vertical_cs", "fieldState": FIELD_NOT_PRESENT, "rawValue": None},
            ]
        )
        self.assertEqual(mapped, "UNKNOWN")
        result = evaluate_generic_height_provenance(_approved(verticalOverrideConfigured=mapped))
        self.assertEqual(result["reasonCode"], REASON_OVERRIDE_NOT_PROVEN)
        self.assertFalse(result["heightGateExecutionAllowed"])
        self.assertNotEqual(result["heightVerticalDatumProvenance"], "AUTO_PASS")

    def test_j_absence_does_not_bypass_other_unknown_gates(self) -> None:
        result = evaluate_generic_height_provenance(
            _approved(
                verticalOverrideConfigured="NO",
                referenceEllipsoidProvenanceStatus="UNKNOWN",
            )
        )
        self.assertEqual(result["reasonCode"], REASON_ELLIPSOID_NOT_PROVEN)
        self.assertFalse(result["heightGateExecutionAllowed"])
        self.assertTrue(VERTICAL_OVERRIDE_ABSENCE_CORRECTION_IMPLEMENTED)

    def test_field_state_tokens_match_rule_c_vocabulary(self) -> None:
        self.assertEqual(HEIGHT_FIELD_NOT_PRESENT, FIELD_NOT_PRESENT)
        self.assertEqual(HEIGHT_FIELD_PRESENT_EMPTY, FIELD_PRESENT_EMPTY)
        self.assertEqual(HEIGHT_FIELD_PRESENT_POPULATED, FIELD_PRESENT_POPULATED)
        self.assertEqual(HEIGHT_FIELD_CONFLICT, FIELD_CONFLICT)
        self.assertEqual(HEIGHT_EVIDENCE_NOT_AVAILABLE, EVIDENCE_NOT_AVAILABLE)
        self.assertTrue(MULTIPLE_OVERRIDE_DESCRIPTOR_CORRECTION_IMPLEMENTED)

    def test_g_jinshidong_real_present_empty(self) -> None:
        incoming = ROOT / "incoming" / "wall_jinshidong_01"
        if not incoming.is_dir():
            self.skipTest("incoming/wall_jinshidong_01 not present")
        artifact = select_stage2_inputs("wall_jinshidong_01", ROOT)
        export = (artifact.get("terraExportRoot") or {}).get("relativePath")
        collected = collect_terra_vertical_evidence(incoming, export)
        rows = _override_rows(collected)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], f"{export}/SDK_Log.txt")
        self.assertEqual(rows[0]["fieldState"], FIELD_PRESENT_EMPTY)
        self.assertEqual(rows[0]["rawValue"], "")
        self.assertEqual(rows[0]["overrideVerticalCsOccurrenceCount"], 1)
        self.assertEqual(rows[0]["rawValues"], [""])
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "NO")
        sources = sources_from_selection(artifact)
        result = evaluate_generic_height_from_sources(incoming, sources)
        self.assertEqual(result["verticalOverrideConfigured"], "NO")
        self.assertEqual(result["heightVerticalDatumProvenance"], "AUTO_PASS")
        self.assertTrue(result["heightGateExecutionAllowed"])

    def test_h_jiulongfeng_selected_pc0_field_not_present(self) -> None:
        incoming = ROOT / "incoming" / "wall_jiulongfeng_01"
        if not incoming.is_dir():
            self.skipTest("incoming/wall_jiulongfeng_01 not present")
        artifact = select_stage2_inputs("wall_jiulongfeng_01", ROOT)
        export = (artifact.get("terraExportRoot") or {}).get("relativePath")
        self.assertEqual(export, "九龙峰森林站大楼/models/pc/0")
        sdk = incoming / export / "SDK_Log.txt"
        self.assertTrue(sdk.is_file())
        self.assertNotIn("override_vertical_cs", sdk.read_text(encoding="utf-8", errors="replace"))
        collected = collect_terra_vertical_evidence(incoming, export)
        rows = _override_rows(collected)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], f"{export}/SDK_Log.txt")
        self.assertEqual(rows[0]["fieldState"], FIELD_NOT_PRESENT)
        self.assertIsNone(rows[0]["rawValue"])
        self.assertEqual(rows[0]["overrideVerticalCsOccurrenceCount"], 0)
        self.assertEqual(rows[0]["rawValues"], [])
        self.assertEqual(vertical_override_state_from_terra_evidence(collected["evidence"]), "NO")
        sibling = incoming / "九龙峰森林站大楼" / "map" / "SDK_Log.txt"
        self.assertTrue(sibling.is_file())
        self.assertIn("override_vertical_cs", sibling.read_text(encoding="utf-8", errors="replace"))


class VerticalOverrideConflictPrecedenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_override_prec_"))
        self.incoming = self.tmp / "incoming" / "wall_test"
        self.dest = self.tmp / "metric_registration"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_terra(self, export_rel: str, sdk_body: str) -> None:
        export = self.incoming / export_rel
        report = export / "report" / "model_report.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(
                {
                    "output coordinate": "WGS 84 / UTM zone 50N",
                    "output vertical coordinate": "Default",
                }
            ),
            encoding="utf-8",
        )
        (export / "SDK_Log.txt").write_text(sdk_body, encoding="utf-8")
        meta = export / "terra_ply" / "metadata.xml"
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<ModelMetadata version=\"1\">\n"
            "<SRS>EPSG:32650</SRS>\n"
            "<SRSOrigin>100.0,200.0,10.0</SRSOrigin>\n"
            "</ModelMetadata>\n",
            encoding="utf-8",
        )

    def _evaluate_from_collector(self, export_rel: str, sdk_body: str) -> tuple[dict, dict, dict]:
        self._write_terra(export_rel, sdk_body)
        collected = collect_terra_vertical_evidence(self.incoming, export_rel)
        projected = height_evidence_from_rule_c_payload(
            {
                "referenceEllipsoid": "WGS84",
                "referenceEllipsoidProvenanceStatus": "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC",
                "specDefaultInvoked": True,
                "mrkEllh": {"valid": True},
                "heightObservationSemantic": "GNSS_GEODETIC_ELLIPSOIDAL_HEIGHT",
                "terraVerticalMode": collected["terraVerticalMode"],
                "geoidConversionConfigured": collected["geoidConversionConfigured"],
                "terraVerticalEvidence": collected["evidence"],
                "policy": "RULE_C_SPEC_GOVERNED_DEFAULT",
            },
            selected_srs_origin=ORIGIN,
            selected_metadata_relative_path=f"{export_rel}/terra_ply/metadata.xml",
            terra_export_root_relative=export_rel,
        )
        result = evaluate_generic_height_provenance(
            {
                **projected,
                "usedSrsOrigin": list(ORIGIN),
                "usedMetadataRelativePath": f"{export_rel}/terra_ply/metadata.xml",
            }
        )
        return collected, projected, result

    def test_e2e_empty_plus_populated_conflict_precedes_geoid(self) -> None:
        collected, projected, result = self._evaluate_from_collector(
            "export0",
            '[I]{"override_vertical_cs":""}\n[I]{"override_vertical_cs":"EGM96"}\n',
        )
        rows = _override_rows(collected)
        self.assertEqual(rows[0]["fieldState"], FIELD_CONFLICT)
        self.assertEqual(collected["geoidConversionConfigured"], "YES")
        self.assertEqual(projected["geoidConversionConfigured"], "YES")
        self.assertEqual(projected["verticalOverrideConfigured"], "UNKNOWN")
        self.assertEqual(projected["verticalOverrideFieldState"], FIELD_CONFLICT)
        self.assertEqual(result["reasonCode"], REASON_OVERRIDE_CONFLICT)
        self.assertEqual(result["heightVerticalDatumProvenance"], "HUMAN_REVIEW_REQUIRED")
        self.assertFalse(result["heightGateExecutionAllowed"])
        self.assertNotEqual(result["reasonCode"], REASON_GEOID_UNSUPPORTED)
        self.assertTrue(VERTICAL_OVERRIDE_CONFLICT_PRECEDENCE_CORRECTION_IMPLEMENTED)

    def test_e2e_different_populated_conflict_precedes_geoid(self) -> None:
        collected, projected, result = self._evaluate_from_collector(
            "export0",
            '[I]{"override_vertical_cs":"EGM96"}\n[I]{"override_vertical_cs":"EPSG:5703"}\n',
        )
        self.assertEqual(_override_rows(collected)[0]["fieldState"], FIELD_CONFLICT)
        self.assertEqual(collected["geoidConversionConfigured"], "YES")
        self.assertEqual(projected["verticalOverrideConfigured"], "UNKNOWN")
        self.assertEqual(result["reasonCode"], REASON_OVERRIDE_CONFLICT)
        self.assertEqual(result["heightVerticalDatumProvenance"], "HUMAN_REVIEW_REQUIRED")
        self.assertFalse(result["heightGateExecutionAllowed"])
        self.assertNotEqual(result["reasonCode"], REASON_GEOID_UNSUPPORTED)

    def test_e2e_conflict_stops_registration_before_sim3(self) -> None:
        self._write_terra(
            "export0",
            '[I]{"override_vertical_cs":""}\n[I]{"override_vertical_cs":"EGM96"}\n',
        )
        collected = collect_terra_vertical_evidence(self.incoming, "export0")
        self.assertEqual(collected["geoidConversionConfigured"], "YES")
        projected = height_evidence_from_rule_c_payload(
            {
                "referenceEllipsoid": "WGS84",
                "referenceEllipsoidProvenanceStatus": "DEFAULT_WGS84_BY_APPROVED_DJI_SPEC",
                "specDefaultInvoked": True,
                "mrkEllh": {"valid": True},
                "heightObservationSemantic": "GNSS_GEODETIC_ELLIPSOIDAL_HEIGHT",
                "terraVerticalMode": collected["terraVerticalMode"],
                "geoidConversionConfigured": collected["geoidConversionConfigured"],
                "terraVerticalEvidence": collected["evidence"],
            },
            selected_srs_origin=ORIGIN,
            selected_metadata_relative_path="export0/terra_ply/metadata.xml",
            terra_export_root_relative="export0",
        )
        sources = Stage2SelectedSources(
            wall_id="wall_test",
            image_relative_paths=("flight/DJI_20260823122200_0001_V.JPG",),
            image_dir_relative="flight",
            mrk_relative_path="flight/x.MRK",
            metadata_xml_relative_path="export0/terra_ply/metadata.xml",
            srs="EPSG:32650",
            srs_origin=(100.0, 200.0, 10.0),
            ply_relative_path=None,
            association_method="test",
            association_rule="test",
            height_provenance_evidence=projected,
        )
        with patch("offline.metric_registration.pipeline.ransac_umeyama") as ransac, patch(
            "offline.metric_registration.pipeline.umeyama"
        ) as umeyama_fn, patch(
            "offline.metric_registration.pipeline.build_correspondences"
        ) as corr:
            corr.side_effect = RuntimeError("REACHED_CORRESPONDENCES")
            ransac.side_effect = AssertionError("SIM3_CALLED")
            umeyama_fn.side_effect = AssertionError("SIM3_CALLED")
            payload = register("wall_test", self.tmp, sources=sources, dest=self.dest)
        ransac.assert_not_called()
        umeyama_fn.assert_not_called()
        corr.assert_not_called()
        self.assertEqual(payload["reasonCode"], REASON_OVERRIDE_CONFLICT)
        self.assertFalse(payload["heightGateExecutionAllowed"])
        self.assertNotIn("scale", payload)
        self.assertNotEqual(payload["reasonCode"], REASON_GEOID_UNSUPPORTED)


if __name__ == "__main__":
    unittest.main()
