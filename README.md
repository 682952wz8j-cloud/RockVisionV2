# RockVision V2

iPhone AR application for outdoor rock climbing.

A climber points the camera at a known wall. The app estimates a validated
visual 6DoF camera pose relative to that wall, then renders known climbing
route polylines at their physical positions.

This repository is a **clean rewrite**. It does not migrate RockVision V1 code
and does not share an Xcode project with V1.

V1 (read-only requirements record): `/Users/zhengzhang/Documents/RockVision`

## Current status

**Gate 0 passed on a physical iPhone. Gate 1A passed. Gate 1B
(source qualification) is implemented.** Later gates are not started.

## Data stages

```text
incoming/wall_<id>/          raw drop: original folders and files
        ↓
  Raw Data Ingestion         inventory.json + validation report
        ↓
offline/work/wall_<id>/      generated intermediates
        ↓
  QA / Geometry Registration
        ↓
walls/wall_<id>/             validated Wall Package
        ↓
WallDataProvider             Bundle now; Cache / Remote later
        ↓
iPhone
```

| Folder | Meaning | Mutable? |
|--------|---------|----------|
| [`incoming/`](incoming/README.md) | Raw source. Original filenames and EXIF. | **No.** Pipeline never writes here. |
| `offline/work/` | Reproducible intermediates. Safe to delete and rebuild. | Generated only. |
| `walls/` | Final Wall Packages. Only input to `WallDataProvider`. | Generated only. |

To add a wall: create `incoming/wall_<id>/`, copy the original export
folders into it (no manual sorting), then run:

```text
./rockvision ingest wall_<id>
./rockvision qualify wall_<id>
```

Details: [incoming/README.md](incoming/README.md).

| Document | Purpose |
|----------|---------|
| [docs/ROCKVISION_V2_ARCHITECTURE.md](docs/ROCKVISION_V2_ARCHITECTURE.md) | System architecture, modules, OpenCV integration, exporter, uncertainties |
| [docs/WALL_PACKAGE_SPEC.md](docs/WALL_PACKAGE_SPEC.md) | Versioned Wall Package schema |
| [docs/COORDINATE_CONVENTIONS.md](docs/COORDINATE_CONVENTIONS.md) | Coordinate frames and `T_A_B` transforms |
| [docs/DEVELOPMENT_GATES.md](docs/DEVELOPMENT_GATES.md) | Sequential development gates |
| [incoming/README.md](incoming/README.md) | How to add a wall (raw drop) |

## Fixed technology stack

| Role | Technology |
|------|------------|
| Offline geometry | COLMAP + SIFT |
| Offline feature export | OpenCV SIFT associated to COLMAP 3D observations |
| iPhone localization | OpenCV SIFT → KNN + ratio test → 2D–3D → `solvePnPRansac` |
| Tracking after lock | ARKit |
| Languages | Swift, Objective-C++ bridge, Python (offline only) |

There is one localization implementation. SuperPoint, LightGlue, SuperGlue,
hloc runtime, Core ML features, and on-device Python/COLMAP are out of scope.

## Pipeline

```text
GPS (coarse only)
  → Crag / Wall candidate selection
  → Load Wall Package
  → Visual Localization (OpenCV SIFT + PnP/RANSAC)
  → multi-frame confirmation
  → T_opencvCam_colmap
  → S_wall_colmap required
  → T_wall_camera
  → T_ARWorld_Wall
  → route rendering
  → ARKit tracking
  → visual relocalization when required
```

`T_wall_camera` and `T_ARWorld_Wall` are **unavailable** while
`S_wall_colmap.status = unknown`. Jiulongfeng is currently unknown.
Gates 2–6 may produce `T_opencvCam_colmap` only. That is not a metric
AR pose.
