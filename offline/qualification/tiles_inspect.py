from __future__ import annotations

import json
import struct
from pathlib import Path

from .status import ProvenanceStatus, claim

MISSING = "missing"


def inspect_b3dm(path: Path) -> dict:
    data = path.read_bytes()[: 64 * 1024]
    if data[:4] != b"b3dm":
        return {"magic": MISSING, "rtcCenter": MISSING, "cesiumRtc": False}
    if len(data) < 28:
        return {"magic": "b3dm", "rtcCenter": MISSING, "cesiumRtc": False}
    _ver, _length, feature_json_len = struct.unpack_from("<III", data, 4)
    feature_json = data[28 : 28 + feature_json_len].decode("utf-8", errors="replace").strip()
    rtc = MISSING
    cesium_rtc = False
    if feature_json:
        try:
            table = json.loads(feature_json)
            if "RTC_CENTER" in table:
                rtc = table["RTC_CENTER"]
        except json.JSONDecodeError:
            pass
    glb_at = data.find(b"glTF")
    if b"CESIUM_RTC" in data[: min(len(data), 8192)]:
        cesium_rtc = True
    return {
        "magic": "b3dm",
        "rtcCenter": rtc,
        "cesiumRtc": cesium_rtc,
        "glbMagicOffset": glb_at if glb_at >= 0 else MISSING,
    }


def sample_b3dm(incoming: Path, rel_paths: list[str], limit: int = 5) -> list[dict]:
    samples = []
    for rel in rel_paths[:limit]:
        path = incoming / rel
        if path.is_file():
            info = inspect_b3dm(path)
            info["relativePath"] = rel
            samples.append(info)
    return samples
