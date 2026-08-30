"""Minimal JPEG + EXIF writer for isolated ingestion fixtures."""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image


def _ascii(value: str) -> bytes:
    data = value.encode("ascii") + b"\x00"
    return data


def _rational(num: int, den: int = 1) -> bytes:
    return struct.pack("<II", num, den)


def _pack_ifd(entries: list[tuple[int, int, int, bytes | None]], data_start: int) -> bytes:
    packed = struct.pack("<H", len(entries))
    overflow = b""
    cursor = data_start
    for tag, typ, count, raw in entries:
        raw = raw or b""
        if len(raw) <= 4:
            value = raw.ljust(4, b"\x00")
        else:
            value = struct.pack("<I", cursor)
            overflow += raw
            cursor += len(raw)
        packed += struct.pack("<HHI", tag, typ, count) + value
    packed += struct.pack("<I", 0)
    return packed + overflow


def build_exif(
    *,
    make: str | None = "TestMake",
    model: str | None = "TestModel",
    timestamp: str | None = "2024:01:02 03:04:05",
    orientation: int | None = 1,
    focal_length: tuple[int, int] | None = (35, 1),
    focal_35mm: int | None = 35,
    gps: tuple[float, float, float] | None = (31.2, 121.5, 100.0),
    gps_map_datum: str | None = None,
) -> bytes:
    tiff_header_len = 8
    # We build IFD0, then Exif IFD, then GPS IFD, then their overflow in one pass
    # using known offsets by assembling backwards from a layout plan.

    TYPE_ASCII = 2
    TYPE_SHORT = 3
    TYPE_LONG = 4
    TYPE_RATIONAL = 5

    def dms(value: float) -> bytes:
        sign = 1 if value >= 0 else -1
        value = abs(value)
        deg = int(value)
        minutes_full = (value - deg) * 60
        minutes = int(minutes_full)
        seconds = round((minutes_full - minutes) * 60 * 10000)
        return _rational(deg, 1) + _rational(minutes, 1) + _rational(seconds, 10000)

    exif_entries: list[tuple[int, int, int, bytes]] = []
    if timestamp:
        exif_entries.append((0x9003, TYPE_ASCII, len(timestamp) + 1, _ascii(timestamp)))
    if focal_length:
        exif_entries.append((0x920A, TYPE_RATIONAL, 1, _rational(*focal_length)))
    if focal_35mm is not None:
        exif_entries.append((0xA405, TYPE_SHORT, 1, struct.pack("<H", focal_35mm)))

    gps_entries: list[tuple[int, int, int, bytes]] = []
    if gps:
        lat, lon, alt = gps
        lat_ref = "N" if lat >= 0 else "S"
        lon_ref = "E" if lon >= 0 else "W"
        gps_entries.append((0x0001, TYPE_ASCII, 2, _ascii(lat_ref)))
        gps_entries.append((0x0002, TYPE_RATIONAL, 3, dms(lat)))
        gps_entries.append((0x0003, TYPE_ASCII, 2, _ascii(lon_ref)))
        gps_entries.append((0x0004, TYPE_RATIONAL, 3, dms(lon)))
        gps_entries.append((0x0006, TYPE_RATIONAL, 1, _rational(int(abs(alt) * 100), 100)))
        if gps_map_datum:
            gps_entries.append(
                (0x0012, TYPE_ASCII, len(gps_map_datum) + 1, _ascii(gps_map_datum))
            )

    # Layout:
    # 0: II*\0 + offset 8
    # 8: IFD0 (count + 12*n + next) + overflow
    # then Exif IFD
    # then GPS IFD
    ifd0_start = tiff_header_len

    def ifd_size(n: int, overflow_len: int) -> int:
        return 2 + 12 * n + 4 + overflow_len

    def overflow_len(entries: list[tuple[int, int, int, bytes]]) -> int:
        return sum(len(raw) for _t, _y, _c, raw in entries if len(raw) > 4)

    # IFD0 entries depend on offsets of later IFDs. Estimate sizes first.
    ifd0_entry_count = sum(
        1
        for item in (make, model, timestamp, orientation, True, bool(gps))
        if item not in {None, False}
    )
    # make, model, datetime, orientation, exif pointer, optional gps pointer
    def stored_overflow(raw: bytes) -> int:
        return len(raw) if len(raw) > 4 else 0

    ifd0_overflow = 0
    if make:
        ifd0_overflow += stored_overflow(_ascii(make))
    if model:
        ifd0_overflow += stored_overflow(_ascii(model))
    if timestamp:
        # DateTime is written as a 20-byte ASCII field
        ifd0_overflow += stored_overflow(_ascii(timestamp)[:20].ljust(20, b"\x00"))
    ifd0_len = ifd_size(ifd0_entry_count, ifd0_overflow)
    exif_start = ifd0_start + ifd0_len
    exif_len = ifd_size(len(exif_entries), overflow_len(exif_entries)) if exif_entries else 0
    gps_start = exif_start + exif_len
    _gps_len = ifd_size(len(gps_entries), overflow_len(gps_entries)) if gps_entries else 0

    ifd0: list[tuple[int, int, int, bytes]] = []
    if make:
        ifd0.append((0x010F, TYPE_ASCII, len(make) + 1, _ascii(make)))
    if model:
        ifd0.append((0x0110, TYPE_ASCII, len(model) + 1, _ascii(model)))
    if orientation is not None:
        ifd0.append((0x0112, TYPE_SHORT, 1, struct.pack("<H", orientation)))
    if timestamp:
        ifd0.append((0x0132, TYPE_ASCII, 20, _ascii(timestamp)[:20].ljust(20, b"\x00")))
    if exif_entries:
        ifd0.append((0x8769, TYPE_LONG, 1, struct.pack("<I", exif_start)))
    if gps_entries:
        ifd0.append((0x8825, TYPE_LONG, 1, struct.pack("<I", gps_start)))

    tiff = b"II*\x00" + struct.pack("<I", ifd0_start)
    tiff += _pack_ifd(ifd0, ifd0_start + 2 + 12 * len(ifd0) + 4)
    if exif_entries:
        tiff += _pack_ifd(exif_entries, exif_start + 2 + 12 * len(exif_entries) + 4)
    if gps_entries:
        tiff += _pack_ifd(gps_entries, gps_start + 2 + 12 * len(gps_entries) + 4)

    app1 = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1


def write_jpeg(
    path: Path,
    *,
    size: tuple[int, int] = (64, 48),
    color: tuple[int, int, int] = (20, 80, 160),
    with_exif: bool = True,
    with_gps: bool = True,
    make: str = "TestMake",
    model: str = "TestModel",
    gps_map_datum: str | None = None,
    xmp: dict[str, str] | None = None,
) -> None:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    jpeg = buffer.getvalue()
    assert jpeg[:2] == b"\xff\xd8"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not with_exif:
        path.write_bytes(jpeg)
        return
    gps = (31.2, 121.5, 100.0) if with_gps else None
    if gps_map_datum and gps is None:
        gps = (0.0, 0.0, 0.0)
    exif = build_exif(make=make, model=model, gps=gps, gps_map_datum=gps_map_datum)
    # Insert APP1 after SOI, before the existing APP0/DQT.
    payload = jpeg[:2] + exif + jpeg[2:]
    if xmp:
        payload = _insert_xmp(payload, xmp)
    path.write_bytes(payload)


def _insert_xmp(jpeg: bytes, attrs: dict[str, str]) -> bytes:
    pairs = " ".join(f'drone-dji:{key}="{value}"' for key, value in attrs.items())
    xmp = (
        '<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f'<rdf:Description xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/" {pairs}/>'
        "</rdf:RDF></x:xmpmeta><?xpacket end=\"w\"?>"
    )
    body = b"http://ns.adobe.com/xap/1.0/\x00" + xmp.encode("utf-8")
    app1 = b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body
    return jpeg[:2] + app1 + jpeg[2:]
