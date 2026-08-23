from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.ingestion.detect import classify
from offline.ingestion.hashing import snapshot_hashes
from offline.ingestion.pipeline import ingest
from offline.ingestion.types import RawAssetType, RunResult, ValidationStatus
from offline.testdata.ingestion.jpeg_exif import write_jpeg

PLY = """ply
format ascii 1.0
element vertex 3
property float x
property float y
property float z
end_header
0 0 0
1 0 0
0 1 0
"""

DXF = """  0
SECTION
  2
HEADER
  0
ENDSEC
  0
SECTION
  2
ENTITIES
  0
POLYLINE
  0
ENDSEC
  0
EOF
"""

POLY = "0 0 0\n1 1 1\n2 0 1\n"
JSON_NOTES = '{"name": "capture notes", "version": 1}\n'
UNKNOWN_BIN = b"\x00\x01\x02XYZ\xff"


def _write(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")


class IngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rv_ingest_"))
        self.incoming = self.tmp / "incoming"
        self.offline = self.tmp / "offline" / "work"
        self.incoming.mkdir(parents=True)
        self.offline.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wall(self, wall_id: str = "wall_fixture") -> Path:
        path = self.incoming / wall_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _ingest(self, wall_id: str = "wall_fixture"):
        return ingest(wall_id, self.tmp)

    def test_jpeg_is_recognized(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "DJI_0001.JPG")
        summary = self._ingest()
        inventory = json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())
        rec = inventory["files"][0]
        self.assertEqual(rec["detectedType"], RawAssetType.IMAGE.value)
        self.assertEqual(rec["image"]["imageFormat"], "JPEG")
        self.assertEqual(rec["image"]["pixelWidth"], 64)
        self.assertEqual(rec["image"]["pixelHeight"], 48)
        self.assertEqual(summary.result, RunResult.PASS)

    def test_exif_is_read(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "cam.jpg", make="DJI", model="FC6540")
        self._ingest()
        rec = json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())["files"][0]
        self.assertEqual(rec["image"]["cameraMake"], "DJI")
        self.assertEqual(rec["image"]["cameraModel"], "FC6540")
        self.assertEqual(rec["image"]["focalLength"], "35.0")
        self.assertEqual(rec["image"]["focalLength35mm"], "35")
        self.assertEqual(rec["image"]["captureTimestamp"], "2024:01:02 03:04:05")
        self.assertEqual(rec["image"]["hasExif"], True)

    def test_gps_present_is_read(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "gps.jpg", with_gps=True)
        self._ingest()
        image = json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())["files"][0]["image"]
        self.assertNotEqual(image["gpsLatitude"], "missing")
        self.assertNotEqual(image["gpsLongitude"], "missing")
        self.assertTrue(image["gpsLatitude"].startswith("31.2"))
        self.assertTrue(image["gpsLongitude"].startswith("121.5"))
        self.assertEqual(image["gpsAltitude"], "100.0")

    def test_gps_absent_is_missing(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "nogps.jpg", with_gps=False)
        summary = self._ingest()
        image = json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())["files"][0]["image"]
        self.assertEqual(image["gpsLatitude"], "missing")
        self.assertEqual(image["gpsLongitude"], "missing")
        self.assertEqual(image["gpsAltitude"], "missing")
        self.assertEqual(summary.result, RunResult.PASS_WITH_WARNINGS)

    def test_model_candidate(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "a.jpg")
        _write(wall / "mesh.ply", PLY)
        self._ingest()
        files = {
            item["filename"]: item
            for item in json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())["files"]
        }
        self.assertEqual(files["mesh.ply"]["detectedType"], RawAssetType.MODEL_3D.value)
        self.assertIn("ply", files["mesh.ply"]["detectionMethod"])

    def test_dxf_and_poly_candidates(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "a.jpg")
        _write(wall / "routes.dxf", DXF)
        _write(wall / "line.poly", POLY)
        self._ingest()
        files = {
            item["filename"]: item
            for item in json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())["files"]
        }
        self.assertEqual(files["routes.dxf"]["detectedType"], RawAssetType.ROUTE_GEOMETRY.value)
        self.assertEqual(files["line.poly"]["detectedType"], RawAssetType.ROUTE_GEOMETRY.value)

    def test_json_is_not_route_by_extension(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "a.jpg")
        _write(wall / "sfm_geo_desc.json", JSON_NOTES)
        self._ingest()
        rec = next(
            item
            for item in json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())["files"]
            if item["filename"] == "sfm_geo_desc.json"
        )
        self.assertEqual(rec["detectedType"], RawAssetType.STRUCTURED_DATA.value)
        self.assertNotEqual(rec["detectedType"], RawAssetType.ROUTE_GEOMETRY.value)

    def test_unknown_file_is_kept(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "a.jpg")
        _write(wall / "mystery.bin", UNKNOWN_BIN)
        self._ingest()
        rec = next(
            item
            for item in json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())["files"]
            if item["filename"] == "mystery.bin"
        )
        self.assertEqual(rec["detectedType"], RawAssetType.UNKNOWN.value)
        self.assertEqual(rec["validationStatus"], ValidationStatus.UNKNOWN.value)

    def test_exact_duplicate_detection(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "flight_a" / "DJI_0001.JPG")
        dest = wall / "flight_b" / "copy.JPG"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wall / "flight_a" / "DJI_0001.JPG", dest)
        summary = self._ingest()
        inventory = json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())
        self.assertEqual(len(inventory["duplicates"]["exactDuplicates"]), 1)
        self.assertEqual(len(inventory["duplicates"]["contentDuplicatesNonZero"]), 1)
        self.assertEqual(inventory["duplicates"]["zeroByteIdentical"], [])
        self.assertGreaterEqual(summary.exact_duplicate_files, 1)
        self.assertEqual(summary.result, RunResult.PASS_WITH_WARNINGS)

    def test_same_filename_different_content(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "a.jpg")
        _write(wall / "flight_a" / "readme.txt", "alpha")
        _write(wall / "flight_b" / "readme.txt", "beta")
        summary = self._ingest()
        inventory = json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())
        self.assertEqual(len(inventory["duplicates"]["sameFilenameDifferentContent"]), 1)
        self.assertEqual(summary.result, RunResult.PASS_WITH_WARNINGS)

    def test_nested_folders_are_scanned(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "DJI_flight_001" / "sub" / "deep" / "DJI_0001.JPG")
        _write(wall / "DJI_flight_001" / "sub" / "deep" / "aux.bin", UNKNOWN_BIN)
        summary = self._ingest()
        paths = {
            item["relativePath"]
            for item in json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())["files"]
        }
        self.assertIn("DJI_flight_001/sub/deep/DJI_0001.JPG", paths)
        self.assertIn("DJI_flight_001/sub/deep/aux.bin", paths)
        self.assertEqual(summary.total_files, 2)

    def test_incoming_hashes_unchanged(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "a.jpg")
        _write(wall / "keep.bin", UNKNOWN_BIN)
        before = snapshot_hashes(wall)
        self._ingest()
        after = snapshot_hashes(wall)
        self.assertEqual(before, after)

    def test_missing_wall_id_fails(self) -> None:
        summary = ingest("wall_does_not_exist", self.tmp)
        self.assertEqual(summary.result, RunResult.FAIL)
        self.assertTrue(any("does not exist" in error for error in summary.errors))
        report = (self.tmp / "offline/work/wall_does_not_exist/ingestion/validation_report.md").read_text()
        self.assertIn("FAIL", report)

    def test_rtk_detected_but_not_parsed(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "a.jpg")
        _write(
            wall / "DJI_0001.MRK",
            "1,0,Lat,31.0,Lon,121.0,Ellh,100.0\n",
        )
        self._ingest()
        rec = next(
            item
            for item in json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())["files"]
            if item["filename"] == "DJI_0001.MRK"
        )
        self.assertEqual(rec["detectedType"], RawAssetType.RTK_GNSS.value)
        self.assertFalse(rec["rtkGnss"]["parsed"])
        self.assertEqual(rec["rtkGnss"]["parseStatus"], "detected but parser not implemented")

    def test_classify_does_not_use_folder_name(self) -> None:
        path = Path("/tmp/photos/secret.bin")
        detected, method, _sig = classify(path, UNKNOWN_BIN)
        self.assertEqual(detected, RawAssetType.UNKNOWN)
        self.assertNotIn("photos", method)

    def test_ingestion_sources_have_no_incoming_writes(self) -> None:
        forbidden = (
            ".unlink(",
            ".rmdir(",
            ".rename(",
            ".write_text(",
            ".write_bytes(",
            "os.remove",
            "os.rename",
            "shutil.move",
            "shutil.rmtree",
        )
        readers = [
            ROOT / "offline/ingestion/detect.py",
            ROOT / "offline/ingestion/hashing.py",
            ROOT / "offline/ingestion/images.py",
            ROOT / "offline/ingestion/scan.py",
            ROOT / "offline/ingestion/geospatial.py",
            ROOT / "offline/ingestion/tilesets.py",
            ROOT / "offline/ingestion/source_trees.py",
        ]
        for path in readers:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{path.name} contains {token}")

    def test_tfw_and_prj_are_geospatial_sidecars(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "a.jpg")
        _write(
            wall / "map" / "dsm.tfw",
            "0.5\n0.0\n0.0\n-0.5\n100.0\n200.0\n",
        )
        _write(
            wall / "map" / "dsm.prj",
            'PROJCS["WGS 84 / UTM zone 50N",GEOGCS["WGS 84",AUTHORITY["EPSG","4326"]],AUTHORITY["EPSG","32650"]]\n',
        )
        _write(wall / "map" / "dsm.tif", b"II*\x00" + b"\x00" * 16)
        self._ingest()
        files = {
            item["filename"]: item
            for item in json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())["files"]
        }
        tfw = files["dsm.tfw"]
        prj = files["dsm.prj"]
        self.assertEqual(tfw["detectedType"], RawAssetType.GEOSPATIAL_SIDECAR.value)
        self.assertEqual(prj["detectedType"], RawAssetType.GEOSPATIAL_SIDECAR.value)
        self.assertEqual(tfw["geospatialSidecar"]["parameters"]["pixelSizeX"], 0.5)
        self.assertEqual(tfw["geospatialSidecar"]["parameters"]["upperLeftY"], 200.0)
        self.assertEqual(tfw["geospatialSidecar"]["associatedRasters"], ["map/dsm.tif"])
        self.assertEqual(prj["geospatialSidecar"]["epsg"], "EPSG:32650")
        self.assertIn("PROJCS", prj["geospatialSidecar"]["wkt"])

    def test_tileset_dataset_is_not_counted_as_many_models(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "a.jpg")
        _write(wall / "mesh.ply", PLY)
        _write(wall / "tiles/tile.b3dm", b"b3dm" + b"\x00" * 16)
        _write(wall / "tiles/orphan.b3dm", b"b3dm" + b"\x01" * 16)
        _write(
            wall / "tiles" / "tileset.json",
            json.dumps(
                {
                    "asset": {"version": "1.0", "gltfUpAxis": "Z"},
                    "geometricError": 10,
                    "root": {
                        "boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
                        "content": {"uri": "tile.b3dm"},
                        "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                    },
                }
            ),
        )
        summary = self._ingest()
        inventory = json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())
        self.assertEqual(summary.standalone_models, 1)
        self.assertEqual(summary.standalone_model_formats, ["ply"])
        self.assertTrue(summary.tileset_json_found)
        self.assertEqual(summary.tileset_datasets, 1)
        self.assertEqual(summary.b3dm_tiles, 2)
        self.assertEqual(summary.b3dm_in_datasets, 1)
        self.assertEqual(summary.b3dm_unreferenced, 1)
        dataset = inventory["datasets"]["cesium3dTiles"][0]
        self.assertEqual(dataset["kind"], "3DTilesDataset")
        self.assertEqual(dataset["b3dmCount"], 1)
        self.assertEqual(dataset["rootTransform"][0], 1)
        files = {item["filename"]: item for item in inventory["files"]}
        self.assertEqual(files["tile.b3dm"]["model3D"]["tilesetPath"], "tiles/tileset.json")
        self.assertEqual(files["orphan.b3dm"]["model3D"]["tilesetPath"], "missing")

    def test_zero_byte_duplicates_are_separated(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "a.jpg")
        _write(wall / "photos/.gitkeep", b"")
        _write(wall / "model/.gitkeep", b"")
        dest = wall / "copy.jpg"
        shutil.copy2(wall / "a.jpg", dest)
        summary = self._ingest()
        inventory = json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())
        self.assertEqual(len(inventory["duplicates"]["zeroByteIdentical"]), 1)
        self.assertEqual(len(inventory["duplicates"]["contentDuplicatesNonZero"]), 1)
        self.assertEqual(summary.zero_byte_duplicate_files, 2)
        self.assertGreaterEqual(summary.nonzero_duplicate_groups, 1)
        warnings = "\n".join(summary.warnings)
        self.assertIn("non-zero content duplicate", warnings)
        self.assertNotIn("zero-byte", warnings.lower())

    def test_unique_wall_scans_incoming_sibling_without_moving(self) -> None:
        wall = self._wall()
        write_jpeg(wall / "inside.jpg")
        sibling = self.incoming / "DJI_202608231218_006_九龙峰"
        sibling.mkdir()
        write_jpeg(sibling / "DJI_20260823122212_0001_V.JPG", make="DJI", model="M4E")
        before_sib = list(sibling.iterdir())
        summary = self._ingest()
        inventory = json.loads((self.tmp / "offline/work/wall_fixture/ingestion/inventory.json").read_text())
        paths = {item["relativePath"] for item in inventory["files"]}
        self.assertIn("inside.jpg", paths)
        self.assertIn("../DJI_202608231218_006_九龙峰/DJI_20260823122212_0001_V.JPG", paths)
        self.assertEqual(summary.total_files, 2)
        self.assertTrue(any(tree["id"].startswith("incoming_sibling:") for tree in inventory["sourceTrees"]))
        self.assertEqual([p.name for p in sibling.iterdir()], [p.name for p in before_sib])
        self.assertTrue((sibling / "DJI_20260823122212_0001_V.JPG").is_file())

    def test_two_walls_do_not_attach_ambiguous_siblings(self) -> None:
        wall = self._wall("wall_alpha")
        other = self._wall("wall_beta")
        write_jpeg(wall / "a.jpg")
        write_jpeg(other / "b.jpg")
        sibling = self.incoming / "0823 iphone拍摄"
        sibling.mkdir()
        write_jpeg(sibling / "IMG_1506.JPG")
        ingest("wall_alpha", self.tmp)
        inventory = json.loads((self.tmp / "offline/work/wall_alpha/ingestion/inventory.json").read_text())
        paths = {item["relativePath"] for item in inventory["files"]}
        self.assertEqual(paths, {"a.jpg"})
        self.assertTrue((sibling / "IMG_1506.JPG").is_file())

    def test_heic_container_metadata_without_pillow_heif(self) -> None:
        from offline.ingestion.images import _heic_exif_tiff, _heic_primary_dimensions

        ispe = (20).to_bytes(4, "big") + b"ispe" + b"\x00" * 4 + (5712).to_bytes(4, "big") + (4284).to_bytes(4, "big")
        tiff = b"MM\x00*\x00\x00\x00\x08"
        blob = b"junkExif\x00\x00nottiff" + ispe + b"Exif\x00\x00" + tiff
        self.assertEqual(_heic_primary_dimensions(blob), (5712, 4284))
        self.assertTrue(_heic_exif_tiff(blob).startswith(b"MM\x00*"))


if __name__ == "__main__":
    unittest.main()

