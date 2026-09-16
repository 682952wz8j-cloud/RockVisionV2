"""Filename metadata for this Jinshidong CloudCompare DXF batch."""

from __future__ import annotations

import re
from pathlib import Path

from .schema import REASON_METADATA_INVALID

FILENAME_RE = re.compile(r"^(?P<name>.+?)\s+(?P<grade>5\.\d+[a-d]?)\.dxf$", re.IGNORECASE)

# Quickdraw counts are not encoded in the DXF stem; they are bound to this
# exact filename batch as provided for the Jinshidong field-test ingest.
FILENAME_METADATA: dict[str, dict] = {
    "水太深 5.12d.dxf": {
        "routeId": "jinshidong_shui_tai_shen",
        "routeName": "水太深",
        "grade": "5.12d",
        "quickdraws": "6+2",
        "boltCount": 6,
        "anchorCount": 2,
    },
    "龙抓手 5.11b.dxf": {
        "routeId": "jinshidong_long_zhua_shou",
        "routeName": "龙抓手",
        "grade": "5.11b",
        "quickdraws": "5+2",
        "boltCount": 5,
        "anchorCount": 2,
    },
    "没想好 5.11b.dxf": {
        "routeId": "jinshidong_mei_xiang_hao",
        "routeName": "没想好",
        "grade": "5.11b",
        "quickdraws": "7+2",
        "boltCount": 7,
        "anchorCount": 2,
    },
    "Lucky Baby 5.7.dxf": {
        "routeId": "jinshidong_lucky_baby",
        "routeName": "Lucky Baby",
        "grade": "5.7",
        "quickdraws": "3+2",
        "boltCount": 3,
        "anchorCount": 2,
    },
}


class RouteMetadataError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def metadata_from_filename(filename: str) -> dict:
    known = FILENAME_METADATA.get(filename)
    match = FILENAME_RE.match(filename)
    if known is None or match is None:
        raise RouteMetadataError(
            REASON_METADATA_INVALID,
            f"filename is not a known Jinshidong route DXF: {filename!r}",
        )
    parsed_name = match.group("name")
    parsed_grade = match.group("grade")
    if parsed_name != known["routeName"] or parsed_grade != known["grade"]:
        raise RouteMetadataError(
            REASON_METADATA_INVALID,
            f"filename metadata mismatch for {filename!r}",
        )
    return {
        "sourceFilename": filename,
        **known,
        "identityBasis": "filename",
    }


def require_known_dxf_names(paths: list[Path]) -> list[dict]:
    names = [path.name for path in paths]
    if len(names) != len(set(names)):
        raise RouteMetadataError(REASON_METADATA_INVALID, "duplicate DXF filenames")
    return [metadata_from_filename(name) for name in names]
