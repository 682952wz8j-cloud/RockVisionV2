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

from offline.qualification.dxf_geom import parse_dxf_polylines
from offline.qualification.geodesy import geographic_to_utm, utm_to_geographic
from offline.qualification.images import classify_image
from offline.qualification.ply_stats import read_ply_header
from offline.qualification.rasters import raster_bounds
from offline.qualification.rtk import parse_mrk, parse_rinex_header
from offline.qualification.status import ProvenanceStatus
from offline.qualification.associate import associate_images_to_mrk
from offline.qualification.sessions import DJI_20260823, IPHONE_20260823, LEGACY_DJI, assign_capture_session


def _image_record(**kwargs) -> dict:
    rec = {
        "relativePath": "photo.jpg",
        "filename": "photo.jpg",
        "extension": ".jpg",
        "detectedType": "image",
        "image": {
            "pixelWidth": 64,
            "pixelHeight": 48,
            "hasExif": False,
            "cameraMake": "missing",
            "cameraModel": "missing",
            "focalLength": "missing",
            "focalLength35mm": "missing",
            "captureTimestamp": "missing",
            "gpsLatitude": "missing",
            "gpsLongitude": "missing",
            "gpsAltitude": "missing",
            "imageFormat": "JPEG",
        },
    }
    rec.update({k: v for k, v in kwargs.items() if k != "image"})
    if "image" in kwargs:
        rec["image"].update(kwargs["image"])
    return rec


class QualificationTests(unittest.TestCase):
    def test_source_image_dji_vs_derived(self) -> None:
        dji = classify_image(
            _image_record(
                relativePath="flight/DJI_20260811104240_0001_V.JPG",
                filename="DJI_20260811104240_0001_V.JPG",
                image={"hasExif": True, "cameraMake": "DJI", "cameraModel": "M4E", "gpsLatitude": "30.1"},
            ),
            set(),
        )
        tile = classify_image(
            _image_record(
                relativePath="map/12/3390/1688.png",
                filename="1688.png",
                extension=".png",
                image={"pixelWidth": 256, "pixelHeight": 256, "imageFormat": "PNG"},
            ),
            set(),
        )
        texture = classify_image(
            _image_record(
                relativePath="terra_ply/BlockR/BlockR_0_0.jpg",
                filename="BlockR_0_0.jpg",
                image={"pixelWidth": 8192, "pixelHeight": 8192},
            ),
            {"BlockR_0_0.jpg"},
        )
        self.assertEqual(dji["role"], "originalCameraImage")
        self.assertTrue(dji["colmapSourceCandidate"])
        self.assertEqual(tile["role"], "derivedModelingImage")
        self.assertFalse(tile["colmapSourceCandidate"])
        self.assertEqual(texture["role"], "textureAsset")
        self.assertFalse(texture["colmapSourceCandidate"])

    def test_derived_images_excluded_from_colmap_list(self) -> None:
        report = classify_image(
            _image_record(
                relativePath="AT/report/reprojection_error_0.jpg",
                filename="reprojection_error_0.jpg",
            ),
            set(),
        )
        self.assertFalse(report["colmapSourceCandidate"])
        self.assertEqual(report["role"], "derivedModelingImage")

    def test_tfw_bounds(self) -> None:
        bounds = raster_bounds(
            10,
            5,
            {
                "pixelSizeX": 2.0,
                "rotationY": 0.0,
                "rotationX": 0.0,
                "pixelSizeY": -2.0,
                "upperLeftX": 100.0,
                "upperLeftY": 200.0,
            },
        )
        self.assertEqual(bounds["minX"], 100.0)
        self.assertEqual(bounds["maxX"], 118.0)
        self.assertEqual(bounds["maxY"], 200.0)
        self.assertEqual(bounds["minY"], 192.0)
        self.assertEqual(bounds["widthMApprox"], 18.0)

    def test_prj_epsg_roundtrip_point(self) -> None:
        lat, lon = 30.12974461, 118.015181617
        e, n = geographic_to_utm(lat, lon, 50)
        lat2, lon2 = utm_to_geographic(e, n, 50, True)
        self.assertAlmostEqual(lat, lat2, places=6)
        self.assertAlmostEqual(lon, lon2, places=6)
        self.assertGreater(e, 500000)
        self.assertGreater(n, 3000000)

    def test_ply_header_bounds_fixture(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="rv_ply_"))
        try:
            path = tmp / "box.ply"
            path.write_text(
                "ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\n"
                "property float y\nproperty float z\nelement face 0\nend_header\n"
                "0 0 0\n1 2 3\n",
                encoding="ascii",
            )
            header = read_ply_header(path)
            self.assertEqual(header["vertexCount"], 2)
            self.assertEqual(header["unitsInHeader"], "missing")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dxf_polyline_extract(self) -> None:
        dxf = """  0
SECTION
  2
ENTITIES
  0
POLYLINE
  0
VERTEX
 10
1.0
 20
2.0
 30
3.0
  0
VERTEX
 10
4.0
 20
5.0
 30
6.0
  0
SEQEND
  0
ENDSEC
"""
        geom = parse_dxf_polylines(dxf)
        self.assertEqual(geom["polylineCount"], 1)
        self.assertEqual(geom["vertexCount"], 2)
        self.assertEqual(geom["vertices"][0]["z"], 3.0)

    def test_mrk_parser(self) -> None:
        text = (
            "1\t286210.250319\t[2431]\t  -158,N\t    32,E\t   109,V\t"
            "30.13023826,Lat\t118.01531378,Lon\t363.438,Ellh\t0.002041, 0.002172, 0.006319\t50,Q\n"
        )
        parsed = parse_mrk(text)
        self.assertEqual(parsed["parseStatus"], "parsed")
        rec = parsed["records"][0]
        self.assertEqual(rec["photoId"], 1)
        self.assertEqual(rec["latitude"], 30.13023826)
        self.assertEqual(rec["ellipsoidalHeight"], 363.438)
        self.assertEqual(rec["heightDatum"], "ellipsoidal")

    def test_rinex_header(self) -> None:
        text = (
            "     3.05           OBSERVATION DATA    M: Mixed            RINEX VERSION / TYPE\n"
            "  2026     8    12     7    29   21.2000000     GPS         TIME OF FIRST OBS   \n"
            "                                                            END OF HEADER       \n"
        )
        parsed = parse_rinex_header(text)
        self.assertEqual(parsed["fileType"], "rinexObs")
        self.assertEqual(parsed["parseStatus"], "parsed")

    def test_timestamp_association_date_mismatch_is_contradicted(self) -> None:
        images = [
            classify_image(
                _image_record(
                    relativePath="DJI_20260811104240_0001_V.JPG",
                    filename="DJI_20260811104240_0001_V.JPG",
                    image={
                        "hasExif": True,
                        "cameraMake": "DJI",
                        "cameraModel": "M4E",
                        "gpsLatitude": "30.13",
                        "gpsLongitude": "118.01",
                    },
                ),
                set(),
            )
        ]
        mrk = [
            {
                "filename": "DJI_20260812152955_0002_D.MRK",
                "fileType": "djiMrk",
                "records": [
                    {
                        "photoId": 1,
                        "latitude": 30.1302,
                        "longitude": 118.0153,
                        "ellipsoidalHeight": 363.4,
                    }
                ],
            }
        ]
        assoc = associate_images_to_mrk(images, mrk)
        self.assertEqual(assoc[0]["association"]["status"], ProvenanceStatus.CONTRADICTED.value)

    def test_status_enum(self) -> None:
        self.assertEqual(ProvenanceStatus.PROVEN.value, "PROVEN")
        self.assertEqual(ProvenanceStatus.UNKNOWN.value, "UNKNOWN")

    def test_iphone_heic_is_original_but_not_auto_colmap(self) -> None:
        heic = classify_image(
            _image_record(
                relativePath="../0823 iphone拍摄/IMG_1507.HEIC",
                filename="IMG_1507.HEIC",
                extension=".heic",
                image={
                    "hasExif": True,
                    "cameraMake": "Apple",
                    "cameraModel": "iPhone 17 Pro",
                    "pixelWidth": 5712,
                    "pixelHeight": 4284,
                    "captureTimestamp": "2026:08:23 12:20:59",
                },
            ),
            set(),
        )
        assign_capture_session(heic)
        self.assertEqual(heic["role"], "originalCameraImage")
        self.assertFalse(heic["colmapSourceCandidate"])
        self.assertEqual(heic["captureSession"], IPHONE_20260823)
        self.assertEqual(heic["sourceDevice"], "iPhone 17 Pro")
        self.assertEqual(heic["captureDate"], "2026-08-23")
        self.assertEqual(heic["qualificationStatus"], ProvenanceStatus.PROVEN.value)

    def test_new_dji_and_legacy_sessions_stay_separate(self) -> None:
        legacy = assign_capture_session(
            classify_image(
                _image_record(
                    relativePath="dji_flight_raw_jiulongfeng/flight_003_area_route/DJI_20260811104240_0001_V.JPG",
                    filename="DJI_20260811104240_0001_V.JPG",
                    image={"hasExif": True, "cameraMake": "DJI", "cameraModel": "M4E"},
                ),
                set(),
            )
        )
        new = assign_capture_session(
            classify_image(
                _image_record(
                    relativePath="../DJI_202608231218_006_九龙峰/DJI_20260823122212_0001_V.JPG",
                    filename="DJI_20260823122212_0001_V.JPG",
                    image={"hasExif": True, "cameraMake": "DJI", "cameraModel": "M4E"},
                ),
                set(),
            )
        )
        self.assertEqual(legacy["captureSession"], LEGACY_DJI)
        self.assertEqual(new["captureSession"], DJI_20260823)
        self.assertNotEqual(legacy["captureSession"], new["captureSession"])

    def test_same_folder_sequence_match_is_proven(self) -> None:
        images = [
            assign_capture_session(
                classify_image(
                    _image_record(
                        relativePath="../DJI_202608231218_006_九龙峰/DJI_20260823122212_0001_V.JPG",
                        filename="DJI_20260823122212_0001_V.JPG",
                        image={
                            "hasExif": True,
                            "cameraMake": "DJI",
                            "cameraModel": "M4E",
                            "gpsLatitude": "30.13003131",
                            "gpsLongitude": "118.01498661",
                        },
                    ),
                    set(),
                )
            )
        ]
        mrk = [
            {
                "filename": "DJI_20260823122214_0002_D.MRK",
                "relativePath": "../DJI_202608231218_006_九龙峰/DJI_20260823122214_0002_D.MRK",
                "fileType": "djiMrk",
                "records": [
                    {
                        "photoId": 1,
                        "latitude": 30.13003131,
                        "longitude": 118.01498663,
                        "ellipsoidalHeight": 326.072,
                    }
                ],
            }
        ]
        assoc = associate_images_to_mrk(images, mrk)
        self.assertEqual(assoc[0]["association"]["status"], ProvenanceStatus.PROVEN.value)
        self.assertTrue(assoc[0]["matchedMrk"])

    def test_same_calendar_date_different_folder_is_not_proven(self) -> None:
        images = [
            classify_image(
                _image_record(
                    relativePath="other_flight/DJI_20260823130000_0001_V.JPG",
                    filename="DJI_20260823130000_0001_V.JPG",
                    image={
                        "hasExif": True,
                        "cameraMake": "DJI",
                        "cameraModel": "M4E",
                        "gpsLatitude": "30.13",
                        "gpsLongitude": "118.01",
                    },
                ),
                set(),
            )
        ]
        mrk = [
            {
                "filename": "DJI_20260823122214_0002_D.MRK",
                "relativePath": "../DJI_202608231218_006_九龙峰/DJI_20260823122214_0002_D.MRK",
                "fileType": "djiMrk",
                "records": [{"photoId": 1, "latitude": 30.13, "longitude": 118.01, "ellipsoidalHeight": 320.0}],
            }
        ]
        assoc = associate_images_to_mrk(images, mrk)
        self.assertNotEqual(assoc[0]["association"]["status"], ProvenanceStatus.PROVEN.value)


if __name__ == "__main__":
    unittest.main()
