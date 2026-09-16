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

from offline.ingestion.hashing import sha256_file
from offline.route_ingestion.discover import discover_route_dxf
from offline.route_ingestion.ingest import polyline_sha256
from offline.route_ingestion.metadata import metadata_from_filename
from offline.route_ingestion.parse import ingest_polyline_from_dxf
from offline.route_ingestion.pipeline import run_route_ingestion
from offline.route_ingestion.schema import GATE_STOP, REASON_METADATA_INVALID
from offline.stage2_selection.discovery import discover_candidates
from offline.stage2_selection.select import select_stage2_inputs
from offline.testdata.ingestion.jpeg_exif import write_jpeg
from offline.wall_build.discovery import build_discovery, scan_wall_records
from offline.wall_build.manifest import build_input_manifest, verify_input_manifest
from offline.wall_build.orchestrator import run_wall_build
from offline.wall_build.states import ReasonCode, StageStatus

JINSHIDONG = "wall_jinshidong_01"
JINSHIDONG_RUN = "wb_20260906T024519Z_6e08b5ff"
JINSHIDONG_FP = "32e9791497d9c9584acf455dc0942762f1d3e1993e9b4e682723408c1294350c"
JINSHIDONG_CAPTURE_009 = "DJI_202609051628_009_九龙峰"


def _cc_dxf(vertices: list[tuple[float, float, float]]) -> str:
    lines = [
        "999",
        "Created by CloudCompare v2.14.beta (Jun 29 2026)",
        "  0",
        "SECTION",
        "  2",
        "HEADER",
        "  0",
        "ENDSEC",
        "  0",
        "SECTION",
        "  2",
        "ENTITIES",
        "  0",
        "POLYLINE",
    ]
    for x, y, z in vertices:
        lines.extend(["  0", "VERTEX", " 10", str(x), " 20", str(y), " 30", str(z)])
    lines.extend(["  0", "SEQEND", "  0", "ENDSEC", "  0", "EOF"])
    return "\n".join(lines) + "\n"


class RouteNamespaceIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _incoming(self, wall_id: str) -> Path:
        incoming = self.tmp / "incoming" / wall_id
        incoming.mkdir(parents=True)
        return incoming

    def test_stage2_discovery_skips_routes_namespace_not_other_files(self) -> None:
        incoming = self._incoming("wall_test_routes_ns")
        write_jpeg(incoming / "keep.jpg")
        (incoming / "routes").mkdir()
        (incoming / "routes" / "Lucky Baby 5.7.dxf").write_text(
            _cc_dxf([(0.0, 0.0, 0.0), (1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]),
            encoding="utf-8",
        )
        (incoming / "notes.txt").write_text("keep unknown", encoding="utf-8")
        found = discover_candidates(incoming)
        rels = {img["relativePath"] for img in found["images"]}
        self.assertIn("keep.jpg", rels)
        self.assertFalse(any(item["relativePath"].startswith("routes/") for item in found["images"]))
        self.assertFalse(any("Lucky Baby" in json.dumps(found) for item in [found]))
        text = json.dumps(found)
        self.assertNotIn("routes/", text)

    def test_input_freeze_excludes_routes_but_still_freezes_capture_files(self) -> None:
        incoming = self._incoming("wall_test_routes_freeze")
        write_jpeg(incoming / "cam.jpg")
        (incoming / "routes").mkdir()
        dxf = incoming / "routes" / "Lucky Baby 5.7.dxf"
        dxf.write_text(_cc_dxf([(0.0, 0.0, 0.0), (1.0, 2.0, 3.0), (2.0, 2.0, 4.0)]), encoding="utf-8")
        manifest = build_input_manifest(
            run_id="wb_test",
            wall_id="wall_test_routes_freeze",
            incoming=incoming,
            run_start_time="2026-09-08T00:00:00Z",
        )
        recorded = {item["relativePath"] for item in manifest["files"]}
        self.assertIn("cam.jpg", recorded)
        self.assertFalse(any(path.startswith("routes/") for path in recorded))
        dxf.write_text(_cc_dxf([(0.0, 0.0, 0.0), (9.0, 9.0, 9.0), (8.0, 8.0, 8.0)]), encoding="utf-8")
        ok, discrepancies = verify_input_manifest(incoming, manifest)
        self.assertTrue(ok, discrepancies)
        (incoming / "cam.jpg").write_bytes(b"mutated-jpeg-bytes-not-a-real-image")
        ok2, disc2 = verify_input_manifest(incoming, manifest)
        self.assertFalse(ok2)
        self.assertTrue(any(item.get("relativePath") == "cam.jpg" for item in disc2))

    def test_wall_build_lists_routes_separately_from_legacy_dxf(self) -> None:
        incoming = self._incoming("wall_test_routes_disc")
        write_jpeg(incoming / "cam.jpg")
        (incoming / "legacy.dxf").write_text(_cc_dxf([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]), encoding="utf-8")
        (incoming / "routes").mkdir()
        (incoming / "routes" / "没想好 5.11b.dxf").write_text(
            _cc_dxf([(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (2.0, 2.0, 2.0)]),
            encoding="utf-8",
        )
        records = scan_wall_records(incoming)
        discovery = build_discovery("wall_test_routes_disc", incoming, records)
        dxf_names = {item["sourceFilename"] for item in discovery["dxfFiles"]}
        route_names = {item["sourceFilename"] for item in discovery["authoritativeRouteInputs"]}
        self.assertEqual(dxf_names, {"legacy.dxf"})
        self.assertEqual(route_names, {"没想好 5.11b.dxf"})
        capture_dirs = {item["relativeDirectory"] for item in discovery["captureCandidates"]}
        self.assertNotIn("routes", capture_dirs)

    def test_routes_dxf_mutation_does_not_fail_wall_build_input_freeze(self) -> None:
        wall_id = "wall_test_routes_mut"
        incoming = self._incoming(wall_id)
        write_jpeg(incoming / "cam.jpg")
        (incoming / "routes").mkdir()
        dxf = incoming / "routes" / "龙抓手 5.11b.dxf"
        dxf.write_text(_cc_dxf([(0.0, 0.0, 0.0), (1.0, 2.0, 3.0), (3.0, 2.0, 1.0)]), encoding="utf-8")
        import offline.ingestion.pipeline as ingest_mod

        real_ingest = ingest_mod.ingest

        def mutate_route(wid, root):
            summary = real_ingest(wid, root)
            path = root / "incoming" / wid / "routes" / "龙抓手 5.11b.dxf"
            path.write_text(_cc_dxf([(0.0, 0.0, 0.0), (4.0, 4.0, 4.0), (5.0, 5.0, 5.0)]), encoding="utf-8")
            return summary

        with (
            patch("offline.wall_build.orchestrator.ingest", side_effect=mutate_route),
            patch("offline.wall_build.stage2_run.reconstruct") as reconstruct,
        ):
            report = run_wall_build(wall_id, self.tmp)
        reconstruct.assert_not_called()
        self.assertEqual(report["stageStatuses"]["INPUT_FREEZE"]["status"], StageStatus.AUTO_PASS.value)
        self.assertNotIn(ReasonCode.INPUT_MUTATED_DURING_RUN.value, report["reasonCodes"])


class RouteGeometryAndMetadataTests(unittest.TestCase):
    def test_gate5a_polyline_hash_matches_frozen_route_test_01(self) -> None:
        ingested = json.loads(
            (ROOT / "validation" / "gate5a" / "gate5a_ingested_route_test_01.json").read_text(encoding="utf-8")
        )
        self.assertEqual(polyline_sha256(ingested["polyline"]), ingested["polylineSha256"])

    def test_dummy_origin_excluded_and_remaining_vertices_unmodified(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        vertices = [(0.0, 0.0, 0.0), (-1.25, 2.5, 3.75), (-1.5, 2.25, 4.0)]
        path = tmp / "Lucky Baby 5.7.dxf"
        path.write_text(_cc_dxf(vertices), encoding="utf-8")
        geom = ingest_polyline_from_dxf(path)
        self.assertTrue(geom["dummyOriginExcluded"])
        self.assertEqual(geom["sourceVertexCount"], 3)
        self.assertEqual(geom["pointCount"], 2)
        self.assertEqual(geom["ingestedVertices"], [[-1.25, 2.5, 3.75], [-1.5, 2.25, 4.0]])

    def test_filename_metadata_for_this_batch(self) -> None:
        meta = metadata_from_filename("水太深 5.12d.dxf")
        self.assertEqual(meta["routeName"], "水太深")
        self.assertEqual(meta["grade"], "5.12d")
        self.assertEqual(meta["quickdraws"], "6+2")
        with self.assertRaises(Exception) as ctx:
            metadata_from_filename("unknown 5.9.dxf")
        self.assertEqual(ctx.exception.code, REASON_METADATA_INVALID)

    def test_discover_does_not_require_per_file_args(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        incoming = tmp / "incoming" / "wall_test_discover"
        routes = incoming / "routes"
        routes.mkdir(parents=True)
        (routes / "Lucky Baby 5.7.dxf").write_text(
            _cc_dxf([(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (2.0, 2.0, 2.0)]),
            encoding="utf-8",
        )
        found = discover_route_dxf(tmp, "wall_test_discover")
        self.assertEqual([item["sourceFilename"] for item in found["dxfFiles"]], ["Lucky Baby 5.7.dxf"])


class JinshidongLiveIsolationTests(unittest.TestCase):
    def test_live_routes_dxf_do_not_enter_stage2_selection(self) -> None:
        incoming = ROOT / "incoming" / JINSHIDONG
        self.assertTrue((incoming / "routes").is_dir())
        unresolved = select_stage2_inputs(JINSHIDONG, ROOT)
        self.assertEqual(unresolved["selectionStatus"], "HUMAN_REVIEW_REQUIRED")
        self.assertIn("MULTIPLE_SELECTABLE_CAPTURE_GROUPS", unresolved["selectionReasonCodes"])
        artifact = select_stage2_inputs(JINSHIDONG, ROOT, capture_group=JINSHIDONG_CAPTURE_009)
        self.assertEqual(artifact["selectionStatus"], "AUTO_PASS")
        checksums = artifact.get("sourceChecksums") or {}
        self.assertTrue(checksums)
        self.assertFalse(any(str(path).startswith("routes/") for path in checksums))
        capture = artifact["selectedCapture"]
        members = capture.get("members") or capture.get("memberRelativePaths") or []
        if members and isinstance(members[0], dict):
            rels = [item.get("relativePath") for item in members]
        else:
            rels = list(members)
        self.assertFalse(any(str(path).startswith("routes/") for path in rels))
        self.assertEqual(capture["parentDirectory"], JINSHIDONG_CAPTURE_009)
        self.assertEqual(capture["memberCount"], 87)


class JinshidongLiveIngestFailClosedTests(unittest.TestCase):
    def test_wrong_fingerprint_does_not_fake_success(self) -> None:
        job = run_route_ingestion(
            wall_id=JINSHIDONG,
            root=ROOT,
            run_id=JINSHIDONG_RUN,
            expected_fingerprint="0" * 64,
        )
        self.assertEqual(job["status"], GATE_STOP)
        self.assertTrue(job.get("reasonCode"))
        self.assertFalse(job.get("published"))
        self.assertFalse(job.get("stage5Release"))


class JinshidongLiveDiscoveryTests(unittest.TestCase):
    def test_discovers_the_four_dxf_without_listing_them(self) -> None:
        found = discover_route_dxf(ROOT, JINSHIDONG)
        names = {item["sourceFilename"] for item in found["dxfFiles"]}
        self.assertEqual(
            names,
            {
                "水太深 5.12d.dxf",
                "龙抓手 5.11b.dxf",
                "没想好 5.11b.dxf",
                "Lucky Baby 5.7.dxf",
            },
        )
        incoming = ROOT / "incoming" / JINSHIDONG
        for item in found["dxfFiles"]:
            path = incoming / item["relativePath"]
            self.assertEqual(item["sha256"], sha256_file(path))


if __name__ == "__main__":
    unittest.main()
