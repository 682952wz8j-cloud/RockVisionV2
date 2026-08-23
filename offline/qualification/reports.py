from __future__ import annotations

import json
from pathlib import Path

from .status import ProvenanceStatus


def write_reports(dest: Path, payload: dict) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if payload.get("result") == "FAIL":
        (dest / "qualification_report.md").write_text(
            "# Qualification Report\n\nFAIL\n\n" + "\n".join(payload.get("errors") or []) + "\n",
            encoding="utf-8",
        )
        return

    images = payload["sourceImages"]
    (dest / "source_images.json").write_text(_dumps(images) + "\n", encoding="utf-8")
    (dest / "capture_sessions.json").write_text(
        _dumps(
            {
                "captureSessions": payload.get("captureSessions"),
                "iphoneQualification": payload.get("iphoneQualification"),
                "colmapReadiness": payload.get("colmapReadiness"),
                "legacyEvidence": payload.get("legacyEvidence"),
                "sourceTrees": payload.get("sourceTrees"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (dest / "rtk_gnss_report.json").write_text(_dumps(payload["rtkGnss"]) + "\n", encoding="utf-8")
    (dest / "camera_georeference.json").write_text(_dumps(payload["cameraGeoreference"]) + "\n", encoding="utf-8")
    (dest / "model_coordinate_report.json").write_text(
        _dumps({"model": payload["model"], "rasters": payload["rasters"], "tiles": payload["tiles"]}) + "\n",
        encoding="utf-8",
    )
    (dest / "route_coordinate_report.json").write_text(_dumps(payload["route"]) + "\n", encoding="utf-8")
    (dest / "coordinate_provenance.md").write_text(_provenance_md(payload), encoding="utf-8")
    (dest / "qualification_report.md").write_text(_qualification_md(payload), encoding="utf-8")


def _dumps(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _qualification_md(payload: dict) -> str:
    lines = [
        "# Gate 1B Qualification Report",
        "",
        f"Wall ID: {payload['wallId']}",
        f"Incoming immutable: {'PASS' if payload.get('incomingUnchanged') else 'FAIL'}",
        f"COLMAP readiness: {(payload.get('colmapReadiness') or {}).get('status', 'UNKNOWN')}",
        "",
        "## Capture sessions",
        "",
        "Legacy 2026-08-11 DJI / 2026-08-12 Terra+RTK evidence is kept separate from 2026-08-23 captures.",
        "",
        _dumps(payload.get("captureSessions")),
        "",
        "## 10 Key Findings",
        "",
    ]
    questions = [
        "真正的 original camera images 有多少？",
        "哪些可以作为未来 COLMAP source images？",
        "为什么只有部分 JPEG 有 GPS？",
        "RTK/GNSS 是否成功解析？",
        "能否建立 image ↔ RTK/GNSS camera position 对应？",
        "PLY 是否已证明为公制？",
        "PLY 是否已证明属于 EPSG:32650？",
        "DXF 是否与 PLY 共享坐标系？",
        "3D Tiles 与 PLY 是否存在已证明的坐标关系？",
        "根据现有证据，未来求 S_wall_colmap 的最佳方案是什么？",
    ]
    for idx, (q, finding) in enumerate(zip(questions, payload.get("findings") or []), start=1):
        lines.append(f"### {idx}. {q}")
        lines.append(f"Status: **{finding['status']}**")
        lines.append(finding["statement"])
        for ev in finding.get("evidence") or []:
            lines.append(f"- {ev}")
        lines.append("")
    rec = payload.get("recommendation") or {}
    lines.extend(["## Metric Wall Frame suggestion", "", _dumps(rec.get("metricWallFrame")), ""])
    lines.extend(["## S_wall_colmap priority", ""])
    for item in rec.get("sWallColmapPriority") or []:
        lines.append(f"- **{item['id']} {item['name']}** — {item['status']}: {item['why']}")
    lines.extend(["", "## Scale vs full Sim(3)", ""])
    for note in rec.get("scaleVsSim3") or []:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def _edge(name: str, status: str, evidence: list[str]) -> str:
    ev = "\n".join(f"  - {item}" for item in evidence)
    return f"**{name}**\nStatus: {status}\nEvidence:\n{ev}\n"


def _provenance_md(payload: dict) -> str:
    findings = payload.get("findings") or []
    def f(i: int) -> dict:
        return findings[i] if i < len(findings) else {"status": "UNKNOWN", "statement": "", "evidence": []}

    images = payload["sourceImages"]
    ply = payload.get("model") or {}
    route = payload.get("route") or {}
    tiles = payload.get("tiles") or {}
    lines = [
        "# Coordinate Provenance",
        "",
        "```text",
        "LEGACY Original Camera Images (3 DJI M4E JPEGs, 2026-08-11)",
        "        │",
        "        │ EXIF GPS: PROVEN positions, unspecified height datum",
        "        │ MRK/RINEX session (2026-08-12): CONTRADICTED as same exposure",
        "        │ This contradiction is historical Gate 1B evidence and still stands.",
        "",
        "NEW 2026-08-23 DJI originals  ←→  2026-08-23 MRK (same folder + sequence)",
        "NEW 2026-08-23 iPhone HEIC    (independent session; not auto-COLMAP)",
        "        ↓",
        "RTK / GNSS Camera Positions",
        "        │",
        "        │ LEGACY: PROVEN one MRK record = sfm_geo_desc.ref_GPS",
        "        │ LEGACY: pairing to the 3 8/11 JPEGs remains CONTRADICTED",
        "        │ NEW: 2026-08-23 image ↔ MRK is reported in capture_sessions.json",
        "        ↓",
        "COLMAP Reconstruction Frame   (not built in Gate 1B)",
        "        │",
        "        │ S_wall_colmap  — not computed",
        "        ↓",
        "Metric Wall Frame  (recommended: local metres at metadata.xml SRSOrigin)",
        "```",
        "",
        "```text",
        "EPSG:32650 rasters (dsm/result)     gsddsm (EPSG:4326)",
        "        │",
        "        │ PROVEN CRS via PRJ; local/global mix must not be collapsed",
        "        ↓",
        "PLY local vertices  ←── T = +SRSOrigin ──→  EPSG:32650",
        "        │",
        "        │ DXF CloudCompare routes: spatial consistency test",
        "        ↓",
        "3D Tiles (child transform vs ECEF of SRSOrigin)",
        "```",
        "",
        _edge("Original images → EXIF GPS", f(2)["status"], f(2).get("evidence") or []),
        _edge("Original images → MRK exposures", f(4)["status"], f(4).get("evidence") or []),
        _edge("MRK → AT / sfm_geo_desc origin", ProvenanceStatus.PROVEN.value, [
            "See rtk_gnss_report.json links when present.",
            str((payload.get("metadata") or {}).get("sfmGeoDesc")),
        ]),
        _edge("PLY → EPSG:32650", f(6)["status"], f(6).get("evidence") or []),
        _edge("PLY metric units", f(5)["status"], f(5).get("evidence") or []),
        _edge("DXF → PLY", f(7)["status"], f(7).get("evidence") or []),
        _edge("3D Tiles → PLY / SRSOrigin", f(8)["status"], f(8).get("evidence") or []),
        _edge("COLMAP → Metric Wall Frame (S_wall_colmap)", ProvenanceStatus.UNKNOWN.value, [
            "COLMAP was not run.",
            "Scale ≠ full Sim(3).",
        ]),
        "",
        "## Frames present",
        "",
        f"- Camera EXIF WGS-84 geographic (3 images). COLMAP candidates: {len(images.get('colmapSourceImages') or [])}",
        f"- DJI MRK geographic + ellipsoidal height",
        f"- RINEX 3.05 mixed GNSS observations/navigation",
        f"- Local ENU declared in sfm_geo_desc.json: { (payload.get('metadata') or {}).get('sfmGeoDesc') }",
        f"- EPSG:32650 + local origin from metadata.xml: {ply.get('modelMetadata')}",
        f"- DXF CloudCompare local XYZ: bbox { (route.get('geometry') or {}).get('boundingBox') }",
        f"- 3D Tiles child transform: {tiles.get('ecefCompare')}",
        "",
    ]
    return "\n".join(lines)
