from __future__ import annotations

import math
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from offline.qualification.ply_stats import (
    PlyDecodeError,
    ply_vertex_bounds,
    ply_vertex_layout,
    read_ply_header,
    read_ply_xyz,
)

PARENT_NEAREST = "6c604c9ed4b3d98db9269fb7b232f6e502e0212f"


def _write_binary_ply(path: Path, properties: list[str], records: bytes, vertex_count: int | None = None) -> None:
    if vertex_count is None:
        vertex_count = 0
        header_probe = (
            "ply\nformat binary_little_endian 1.0\nelement vertex 0\n"
            + "".join(f"{p}\n" for p in properties)
            + "end_header\n"
        ).encode("ascii")
        layout_header = {
            "format": "binary_little_endian",
            "vertexCount": 0,
            "headerBytes": len(header_probe),
            "vertexProperties": properties,
        }
        stride = ply_vertex_layout(layout_header).stride
        vertex_count = len(records) // stride if stride else 0
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {vertex_count}\n"
        + "".join(f"{p}\n" for p in properties)
        + "end_header\n"
    ).encode("ascii")
    path.write_bytes(header + records)


class PlyVertexDecoderTests(unittest.TestCase):
    def test_a_xyz_float32_stride_12(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv_ply_") as tmp:
            path = Path(tmp) / "xyz.ply"
            records = struct.pack("<fff", 1.0, 2.0, 3.0) + struct.pack("<fff", 4.0, 5.0, 6.0)
            _write_binary_ply(
                path,
                ["property float x", "property float y", "property float z"],
                records,
                vertex_count=2,
            )
            header = read_ply_header(path)
            layout = ply_vertex_layout(header)
            self.assertEqual(layout.stride, 12)
            self.assertEqual(read_ply_xyz(path, header), [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])

    def test_b_xyz_uchar_rgb_stride_15(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv_ply_") as tmp:
            path = Path(tmp) / "xyzrgb.ply"
            records = struct.pack("<fffBBB", 10.5, -2.25, 8.0, 255, 0, 128)
            _write_binary_ply(
                path,
                [
                    "property float x",
                    "property float y",
                    "property float z",
                    "property uchar red",
                    "property uchar green",
                    "property uchar blue",
                ],
                records,
                vertex_count=1,
            )
            header = read_ply_header(path)
            layout = ply_vertex_layout(header)
            self.assertEqual(layout.stride, 15)
            self.assertEqual(layout.x_offset, 0)
            self.assertEqual(layout.y_offset, 4)
            self.assertEqual(layout.z_offset, 8)
            self.assertEqual(read_ply_xyz(path, header), [(10.5, -2.25, 8.0)])

    def test_c_xyzrgb_vertices_stay_aligned(self) -> None:
        verts = [
            (1.0, 2.0, 3.0, 255, 128, 1),
            (100.0, 200.0, 300.0, 0, 255, 0),
            (-7.5, 0.125, 42.0, 0, 0, 255),
        ]
        with tempfile.TemporaryDirectory(prefix="rv_ply_") as tmp:
            path = Path(tmp) / "multi.ply"
            records = b"".join(struct.pack("<fffBBB", *v) for v in verts)
            _write_binary_ply(
                path,
                [
                    "property float x",
                    "property float y",
                    "property float z",
                    "property uchar red",
                    "property uchar green",
                    "property uchar blue",
                ],
                records,
                vertex_count=3,
            )
            header = read_ply_header(path)
            decoded = read_ply_xyz(path, header)
            self.assertEqual(len(decoded), 3)
            self.assertEqual(decoded[0], (1.0, 2.0, 3.0))
            self.assertEqual(decoded[1], (100.0, 200.0, 300.0))
            self.assertEqual(decoded[2], (-7.5, 0.125, 42.0))
            old_v1 = struct.unpack_from("<fff", records, 12)
            old_v2 = struct.unpack_from("<fff", records, 24)
            self.assertNotEqual(old_v1, (100.0, 200.0, 300.0))
            self.assertNotEqual(old_v2, (-7.5, 0.125, 42.0))
            self.assertFalse(math.isclose(old_v1[0], 100.0, rel_tol=0.0, abs_tol=1.0))
            self.assertFalse(math.isclose(old_v2[0], -7.5, rel_tol=0.0, abs_tol=1.0))

    def test_d_xyzrgb_bounds(self) -> None:
        verts = [
            (1.0, 10.0, -4.0, 1, 2, 3),
            (5.0, -2.0, 8.0, 254, 253, 252),
            (3.0, 7.0, 0.0, 10, 20, 30),
        ]
        with tempfile.TemporaryDirectory(prefix="rv_ply_") as tmp:
            path = Path(tmp) / "bounds.ply"
            records = b"".join(struct.pack("<fffBBB", *v) for v in verts)
            _write_binary_ply(
                path,
                [
                    "property float x",
                    "property float y",
                    "property float z",
                    "property uchar red",
                    "property uchar green",
                    "property uchar blue",
                ],
                records,
                vertex_count=3,
            )
            header = read_ply_header(path)
            bounds = ply_vertex_bounds(path, header)
            self.assertEqual(bounds["status"], "ok")
            self.assertEqual(bounds["min"], {"x": 1.0, "y": -2.0, "z": -4.0})
            self.assertEqual(bounds["max"], {"x": 5.0, "y": 10.0, "z": 8.0})
            self.assertEqual(bounds["extent"], {"x": 4.0, "y": 12.0, "z": 12.0})

    def test_e_rgb_bytes_do_not_contaminate_xyz(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv_ply_") as tmp:
            path = Path(tmp) / "rgb.ply"
            records = struct.pack("<fffBBB", 0.0, 0.0, 0.0, 255, 255, 255) + struct.pack(
                "<fffBBB", 1.0, 1.0, 1.0, 255, 255, 255
            )
            _write_binary_ply(
                path,
                [
                    "property float x",
                    "property float y",
                    "property float z",
                    "property uchar red",
                    "property uchar green",
                    "property uchar blue",
                ],
                records,
                vertex_count=2,
            )
            header = read_ply_header(path)
            decoded = read_ply_xyz(path, header)
            self.assertEqual(decoded[0], (0.0, 0.0, 0.0))
            self.assertEqual(decoded[1], (1.0, 1.0, 1.0))
            for value in decoded[0] + decoded[1]:
                self.assertTrue(math.isfinite(value))
                self.assertLessEqual(abs(value), 1.0)

    def test_f_truncated_payload_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv_ply_") as tmp:
            path = Path(tmp) / "trunc.ply"
            records = struct.pack("<fffBBB", 1.0, 2.0, 3.0, 4, 5, 6)
            _write_binary_ply(
                path,
                [
                    "property float x",
                    "property float y",
                    "property float z",
                    "property uchar red",
                    "property uchar green",
                    "property uchar blue",
                ],
                records,
                vertex_count=2,
            )
            header = read_ply_header(path)
            self.assertEqual(header["vertexCount"], 2)
            with self.assertRaises(PlyDecodeError) as bounds_err:
                ply_vertex_bounds(path, header)
            self.assertIn("shorter than header count", str(bounds_err.exception))
            with self.assertRaises(PlyDecodeError) as xyz_err:
                read_ply_xyz(path, header)
            self.assertIn("shorter than header count", str(xyz_err.exception))

    def test_g_unsupported_xyz_layout_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv_ply_") as tmp:
            missing_z = Path(tmp) / "no_z.ply"
            _write_binary_ply(
                missing_z,
                ["property float x", "property float y", "property uchar red"],
                struct.pack("<ffB", 1.0, 2.0, 9),
                vertex_count=1,
            )
            with self.assertRaises(PlyDecodeError):
                ply_vertex_layout(read_ply_header(missing_z))
            with self.assertRaises(PlyDecodeError):
                ply_vertex_bounds(missing_z, read_ply_header(missing_z))

            list_x = Path(tmp) / "list_x.ply"
            header_text = (
                "ply\nformat binary_little_endian 1.0\nelement vertex 1\n"
                "property list uchar float x\nproperty float y\nproperty float z\nend_header\n"
            ).encode("ascii")
            list_x.write_bytes(header_text + b"\x00" * 16)
            with self.assertRaises(PlyDecodeError):
                ply_vertex_layout(read_ply_header(list_x))

            bad_type = Path(tmp) / "bad_type.ply"
            header_text = (
                "ply\nformat binary_little_endian 1.0\nelement vertex 1\n"
                "property string x\nproperty float y\nproperty float z\nend_header\n"
            ).encode("ascii")
            bad_type.write_bytes(header_text + b"\x00" * 16)
            with self.assertRaises(PlyDecodeError):
                ply_vertex_layout(read_ply_header(bad_type))

    def test_xyz_after_rgb_uses_declared_offsets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv_ply_") as tmp:
            path = Path(tmp) / "rgb_then_xyz.ply"
            records = struct.pack("<BBB", 9, 8, 7) + struct.pack("<fff", 11.0, 12.0, 13.0)
            _write_binary_ply(
                path,
                [
                    "property uchar red",
                    "property uchar green",
                    "property uchar blue",
                    "property float x",
                    "property float y",
                    "property float z",
                ],
                records,
                vertex_count=1,
            )
            header = read_ply_header(path)
            layout = ply_vertex_layout(header)
            self.assertEqual(layout.stride, 15)
            self.assertEqual(layout.x_offset, 3)
            self.assertEqual(read_ply_xyz(path, header), [(11.0, 12.0, 13.0)])

    def test_double_xyz_not_assumed_float32(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rv_ply_") as tmp:
            path = Path(tmp) / "double.ply"
            records = struct.pack("<ddd", 1.5, 2.5, 3.5)
            _write_binary_ply(
                path,
                ["property double x", "property double y", "property double z"],
                records,
                vertex_count=1,
            )
            header = read_ply_header(path)
            layout = ply_vertex_layout(header)
            self.assertEqual(layout.stride, 24)
            self.assertEqual(read_ply_xyz(path, header), [(1.5, 2.5, 3.5)])

    def test_h_nearest_py_matches_parent_6c604c9(self) -> None:
        current = (ROOT / "offline" / "qualification" / "nearest.py").read_bytes()
        parent = subprocess.check_output(
            ["git", "show", f"{PARENT_NEAREST}:offline/qualification/nearest.py"],
            cwd=ROOT,
        )
        self.assertEqual(current, parent)
        text = current.decode("utf-8")
        self.assertNotIn("_MAX_NEAREST_CLOUD", text)
        self.assertNotIn("_MAX_NEAREST_QUERIES", text)
        self.assertNotIn("math.isfinite", text)


if __name__ == "__main__":
    unittest.main()
