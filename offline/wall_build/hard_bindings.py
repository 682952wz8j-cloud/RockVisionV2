"""Hard-binding audit for the next Stage 2 genericization Development Gate.

Phase 1 records these bindings. It does not delete or genericize them.
"""

from __future__ import annotations

HARD_BINDING_AUDIT = {
    "purpose": "Future GENERIC STAGE 2 INPUT / SESSION PARAMETERIZATION Development Gate scope.",
    "phase1Action": "RECORD_ONLY",
    "bindings": [
        {
            "id": "DJI_CAPTURE_DIR",
            "path": "offline/colmap/layout.py",
            "value": "DJI_202608231218_006_九龙峰",
            "kind": "capture-specific",
        },
        {
            "id": "REQUIRED_SESSION",
            "path": "offline/colmap/layout.py",
            "value": "dji_20260823",
            "kind": "session-specific",
        },
        {
            "id": "IPHONE_CAPTURE_DIR",
            "path": "offline/colmap/layout.py",
            "value": "0823 iphone拍摄",
            "kind": "capture-specific",
        },
        {
            "id": "MRK_HARD_PATH",
            "path": "offline/metric_registration/correspondences.py",
            "value": "DJI_202608231218_006_九龙峰/DJI_20260823122214_0002_D.MRK",
            "kind": "MRK-specific",
        },
        {
            "id": "METADATA_XML",
            "path": "offline/metric_registration/frames.py",
            "value": "九龙峰森林站大楼/models/pc/0/terra_ply/metadata.xml",
            "kind": "SRSOrigin-specific",
        },
        {
            "id": "PLY_RELATIVE",
            "path": "offline/metric_registration/ply_crosscheck.py",
            "value": "九龙峰森林站大楼/models/pc/0/terra_ply/BlockR/BlockR.ply",
            "kind": "path-specific",
        },
        {
            "id": "SFM_GEO_DESC",
            "path": "offline/metric_registration/height_datum.py",
            "value": "九龙峰森林站大楼/AT/sfm_geo_desc.json",
            "kind": "path-specific",
        },
        {
            "id": "QUALIFY_DJI_20260823_READINESS",
            "path": "offline/qualification/sessions.py",
            "value": "colmap_readiness requires captureSession dji_20260823",
            "kind": "session-specific",
        },
        {
            "id": "QUALIFY_TILESET_JIULONGFENG_PATH",
            "path": "offline/qualification/pipeline.py",
            "value": "九龙峰森林站大楼/models/pc/0/terra_b3dms/BlockR/tileset.json",
            "kind": "path-specific",
        },
        {
            "id": "PNP_DEFAULT_WALL_ID",
            "path": "tools/rockvision.py",
            "value": "wall_jiulongfeng_01",
            "kind": "wall-specific",
        },
        {
            "id": "RANSAC_SEED_20260823",
            "path": "offline/metric_registration/pipeline.py",
            "value": "20260823",
            "kind": "date-specific",
            "note": "Solver seed, not capture selection. Do not change in Phase 1.",
        },
    ],
}
