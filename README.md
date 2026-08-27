# RockVision V2

iPhone AR application for outdoor rock climbing.

A climber points the camera at a **known** wall. The app must estimate a
validated **visual** 6DoF camera pose relative to that wall, then render
known climbing route polylines at their physical positions.

This repository is a **clean rewrite**. It does not migrate RockVision V1
code and does not share an Xcode project with V1.

V1 (read-only requirements record): `/Users/zhengzhang/Documents/RockVision`

This README is the **status and architecture entry** for humans and
agents. It answers four questions: what the product is, what the current
architecture is, where development is, and what is allowed next.

It records **Stage / Gate status only**. Detailed experiment numbers,
Field Test tables, and lab notes do not belong here.

**Status source of truth: this file.** Sequential-gate *policy* and the
early Gate 0–11 plan live in
[`docs/DEVELOPMENT_GATES.md`](docs/DEVELOPMENT_GATES.md). That file’s
top **Current position** is synced with this README. Its later Gate 0–11
chapters are historical numbering — see that file’s live-numbering note.

---

## Current Development Status

```text
Stage 1 — iPhone Runtime Foundation          PASS
Stage 2 — Metric Wall Reference Map          PASS
         S_wall_colmap                       VALIDATED
Stage 3 — Visual Localization                PASS (current Gate requirements)
  Gate 3A — OpenCV iOS                       PASS / CLOSED
  Gate 3B — SIFT extraction                  PASS / CLOSED
  Gate 3C — Reference Matching               PASS / CLOSED
  Gate 3D — Single-frame PnP                 PASS / CLOSED
  Gate 3E — Multi-frame confirmation         PASS / CLOSED
           formal field: gate3e_20260825_084148
           failed (do not reuse): gate3e_20260825_065523
Stage 4 — AR Alignment                       PASS
  Gate 4A — SAME-FRAME / LIFETIME            PASS / CLOSED
           formal field: gate4a_20260825_104607
  Gate 4A — METRIC ALIGNMENT                 PASS / CLOSED
  Gate 4B                                  PASS / CLOSED
                                           landmarks FROZEN (W01–W04);
                                           AR physical measurement PASS
                                           (visual identity, 2026-08-27)
Stage 5 — Route AR                           OPEN / IN PROGRESS
                                           explicitly opened 2026-08-27
                                           Gate 5A PASS / CLOSED
                                           GATE_5A_PASS = YES
                                           First route FROZEN (route_test_01)
                                           Gate 5B PASS / CLOSED
                                           GATE_5B_PASS = YES
                                           Gate 5C PASS / CLOSED
                                           GATE_5C_PASS = YES
                                           Route runtime data binding PASS
                                           Route package NOT CREATED
                                           Route rendering NOT STARTED
                                           Gate 5D–5E NOT STARTED
                                           Stage 5 NOT PASS
```

| Stage | Meaning | Status |
|-------|---------|--------|
| 1 | Clean iOS app, ARKit session, camera frames | **PASS** |
| 2 | COLMAP reconstruction + `S_wall_colmap` | **PASS** (`S_wall_colmap` **VALIDATED**) |
| 3 | Visual query → matches → confirmed `T_opencvCam_colmap` | **PASS** (Gates 3A–3E current requirements) |
| 4 | `T_ARWorld_Wall` / metric AR alignment | **PASS** — Gate 4A **PASS / CLOSED**; Gate 4B landmarks **FROZEN**, AR physical measurement **PASS / CLOSED** (`validation/gate4b/gate4b_ar_physical_measurement.json`) |
| 5 | Route polylines in AR | **OPEN / IN PROGRESS** (opened 2026-08-27). Gate 5A **PASS / CLOSED**. First route **FROZEN** (`route_test_01`). Gate 5B **PASS / CLOSED**. Gate 5C **PASS / CLOSED** (rolling current production alignment). Route package **NOT CREATED / NOT AUTHORIZED**. Route rendering **NOT STARTED / NOT AUTHORIZED**. Gate 5D–5E **NOT STARTED / NOT AUTHORIZED**. Stage 5 **NOT PASS** |

Stage 2 **PASS** and `S_wall_colmap` **VALIDATED** clear the Sim(3)
prerequisite. Gate 4A **PASS / CLOSED** means production `T_ARWorld_Wall`
is the metric SE(3) product. That is **not** persistent world lock and
**not** permission to render routes.

Stage 3 sub-gates:

| Gate | Name | Status |
|------|------|--------|
| 3A | OpenCV iOS integration | **PASS / CLOSED** |
| 3B | SIFT extraction on ARFrame | **PASS / CLOSED** |
| 3C | Reference matching | **PASS / CLOSED** |
| 3D | Single-frame PnP / `T_opencvCam_colmap` | **PASS / CLOSED** |
| 3E | Multi-frame confirmation | **PASS / CLOSED** — formal field `gate3e_20260825_084148`. Failed session `gate3e_20260825_065523` remains FAIL. |

Stage 4 sub-gates:

| Gate | Name | Status |
|------|------|--------|
| 4A same-frame / lifetime | Rolling `T_ARWorld_Wall` from confirmed last-frame pose + same ARFrame | **PASS / CLOSED** — formal field `gate4a_20260825_104607` |
| 4A metric alignment | Wall meters → ARWorld meters SE(3) | **PASS / CLOSED** |
| 4B | Metric Wall geometry in ARWorld | **PASS / CLOSED** — landmarks **FROZEN** (`validation/gate4b/gate4b_landmarks_frozen.json`, W01–W04); AR physical measurement **PASS** (`validation/gate4b/gate4b_ar_physical_measurement.json`, visual identity 2026-08-27) |

---

## Current Gate

**Gate 4A — PASS / CLOSED** (same-frame / lifetime and metric SE(3)).

**Gate 4B — PASS / CLOSED** (landmarks FROZEN W01–W04; AR physical measurement PASS, visual identity 2026-08-27).

**Stage 5 — OPEN / IN PROGRESS** (explicitly opened 2026-08-27). Gate 5A **PASS / CLOSED**. First route **FROZEN** (`route_test_01`). Gate 5B **PASS / CLOSED**. Gate 5C **PASS / CLOSED**. Route runtime data binding **PASS** (rolling current production alignment). Route package **NOT CREATED / NOT AUTHORIZED**. Route rendering **NOT STARTED / NOT AUTHORIZED**. Gate 5D–5E **NOT STARTED / NOT AUTHORIZED**. Stage 5 **NOT PASS**.

Canonical ingested polyline: `validation/gate5a/gate5a_ingested_route_test_01.json` (geometry object; `gate5aPass` false; `FIRST_ROUTE_FROZEN` false). Gate 5A PASS closure: `validation/gate5a/gate5a_pass_closure_route_test_01.json`. Gate 5B transform correctness: `validation/gate5b/gate5b_route_transform_correctness_route_test_01.json`. Gate 5C runtime route binding: `validation/gate5c/gate5c_runtime_route_binding_route_test_01.json`. `GATE_5A_INPUT_READY = YES`. `DXF_TO_BLOCKR_RELATION = IDENTITY_PROVEN`. `WallMetricMeters = PROVEN`. `GATE_5A_PASS = YES`. `GATE_5B_PASS = YES`. `GATE_5C_PASS = YES`. That is **not** production Wall Package `routes.json` authorization and **not** route-rendering authorization.

Gate 5A provenance re-audit of `route_test_01` is recorded in `validation/gate5a/gate5a_provenance_reaudit_route_test_01.json` (audit only; not a route package; not PASS). Accepted: `GATE_5A_INPUT_READY = YES`.

Gate 5A identity evidence upgrade of `route_test_01` is recorded in `validation/gate5a/gate5a_identity_evidence_upgrade_route_test_01.json`. Direct CloudCompare object-property reads (2026-08-27) show BlockR Vertices and Polyline Vertices both have Global shift `(0,0,0)` and Global scale `1`. That upgrade established `DXF_TO_BLOCKR_RELATION = IDENTITY_PROVEN` and `WallMetricMeters = PROVEN`. Historical closure remaining `IDENTITY_SUPPORTED` is `validation/gate5a/gate5a_provenance_closure_route_test_01.json`. Historical start audit of the old DXF remains `validation/gate5a/gate5a_provenance_audit.json`.

Formal provenance:

- Gate 3E field session: `gate3e_20260825_084148`
- Do **not** use failed `gate3e_20260825_065523` (session-boundary /
  `qualifiedCount=19`)
- Gate 4A field session (same-frame / lifetime): `gate4a_20260825_104607`
- Gate 4B AR physical measurement: `validation/gate4b/gate4b_ar_physical_measurement.json` (2026-08-27 visual identity; supporting Field Test `gate4b_20260827_121932`)
- Gate 5A provenance audit of old `test routes.dxf` (historical start checkpoint; not this round’s input): `validation/gate5a/gate5a_provenance_audit.json`
- Gate 5A provenance re-audit of `route_test_01` (audit only; not a route package; not PASS): `validation/gate5a/gate5a_provenance_reaudit_route_test_01.json`
- Gate 5A provenance closure of `route_test_01` (historical; identity then `IDENTITY_SUPPORTED`): `validation/gate5a/gate5a_provenance_closure_route_test_01.json`
- Gate 5A identity evidence upgrade of `route_test_01` (`IDENTITY_PROVEN` / WallMetricMeters **PROVEN**): `validation/gate5a/gate5a_identity_evidence_upgrade_route_test_01.json`
- Gate 5A canonical ingested polyline (`route_test_01`; not a production package): `validation/gate5a/gate5a_ingested_route_test_01.json`
- Gate 5A PASS closure: `validation/gate5a/gate5a_pass_closure_route_test_01.json`
- Gate 5B route transform correctness (`route_test_01`): `validation/gate5b/gate5b_route_transform_correctness_route_test_01.json`
- Gate 5C runtime route binding (`route_test_01`; rolling current production alignment; not rendering): `validation/gate5c/gate5c_runtime_route_binding_route_test_01.json`

Production output (when Localization = localized):

```text
T_ARWorld_Wall =
    T_ARWorld_arkitCam
  * T_arkitCam_opencvCam
  * T_opencvCamMeters_wall
```

`T_opencvCamMeters_wall` is SE(3): Wall meters → OpenCV camera meters.
`renderedRoute = false`. Alignment is rolling and instantaneous; lock
loss clears `T_ARWorld_Wall` immediately. This is **not** persistent
Wall↔ARWorld lock.

Gate 4B Layer 1 origin + 1 m XYZ debug geometry consumes that production
`T` only. Formal landmarks W01–W04 are **FROZEN** in
`validation/gate4b/gate4b_landmarks_frozen.json`. On 2026-08-27 the four
predicted marker centers were visually flush to the intended physical
corners after 3D-model identity confirmation. That is Gate 4B PASS.
It is **not** persistent Wall↔ARWorld lock and **not** permission to
render routes.

**Current discipline** (Stage 5 **OPEN / IN PROGRESS**; Gate 5A **PASS / CLOSED**; first route **FROZEN** (`route_test_01`); Gate 5B **PASS / CLOSED**; Gate 5C **PASS / CLOSED**; route rendering **NOT AUTHORIZED**):

- Do not reselect, replace, or optimize frozen W01–W04
- Do not tune scale, offset, flip, or `T_ARWorld_Wall` from marker appearance
- Do not create a production route package / `routes.json` without a later explicit protocol
- Do not start Gate 5D without a later explicit protocol
- Do not start route rendering
- Do not cache ARWorld route points independently of current production alignment
- Do not implement persistent world lock
- Do not restore `T_opencvCam_colmap * inverse(S)` as camera SE(3)

---

## GPS Hard Constraint

1. GPS is allowed **only** for coarse Wall ID / candidate selection.
2. After Wall ID is known, precise localization must be entirely visual.
3. **GPS must never participate in precise camera pose estimation.**
4. GPS, manual T/R/S, a hard-coded pose, or a hand-authored Sim(3) must
   not be used to fake visual-localization success.
5. The Visual Localization path must not use `CLLocation` as pose.

GPS is finished once a wall is selected. After that, pose is visual.

---

## Non-negotiable Architecture Constraints

1. Stage 3 current output is confirmed `T_opencvCam_colmap` (last-frame
   refined candidate in the confirmation window).
2. No manual T/R/S alignment is accepted as localization.
3. No hard-coded pose may be used to pass a localization gate.
4. Gate 4A / 4B CLOSED is **not** persistent Wall↔ARWorld lock and
   **not** permission to render routes.
5. There is **one** current localization path. Do not reopen SuperPoint /
   hloc / LightGlue / Core ML as an iPhone implementation.
6. `T_ARWorld_Wall` is produced only by
   `CoordinateTransforms.productionAlignment(...)`.

---

## Current Architecture

This is the **only** valid production path.

```text
GPS (coarse Wall ID candidates only)
  → Wall ID
  → visual query: OpenCV SIFT                         [implemented]
  → COLMAP observations / Point3D
  → reference matching                                [implemented]
  → accepted unique Point3D correspondences
  → PnP / RANSAC / RefineLM                           [implemented]
  → T_opencvCam_colmap                                [implemented]
  → Gate 3E confirmation (last-frame pose)            [implemented]
  → S_wall_colmap (VALIDATED)
  → productionAlignment → T_ARWorld_Wall              [Gate 4A CLOSED]
  → Gate 4B diagnostic origin + 1 m axes              [present]
  → Gate 4B landmarks W01–W04                         [FROZEN; validation/gate4b]
  → Gate 4B physical measurement                      [PASS]
  → route rendering                                   [Stage 5 OPEN / IN PROGRESS; Gate 5A PASS / CLOSED; first route FROZEN; Gate 5B PASS / CLOSED; Gate 5C PASS / CLOSED rolling bind; package NOT AUTHORIZED; rendering NOT AUTHORIZED; Gate 5D NOT STARTED]
```

Gate 3C loads a **development fixture**, not a production Wall Package.

`cv::solvePnPRansac` runs on **full** `pnpCorrespondences`. Diagnostic
top-20 matches never enter PnP.

ARKit answers: *how has the camera moved since this frame?*
Visual localization answers: *where is the camera relative to the known wall?*
`T_ARWorld_Wall` is recomputed while localized and cleared on loss. That
is not a persistent world lock.

---

## Current Stage 3 stack

Frozen. Do not float versions or swap algorithms inside a gate.

| Role | Current |
|------|---------|
| Device (verified) | iPhone 17 Pro |
| iPhone vision | OpenCV **4.14.0** (`0654a42e19215ef25b1d367d822f3c630447e7c7`) |
| Query SIFT | `nfeatures=0`, `nOctaveLayers=3`, `contrastThreshold=0.04`, `edgeThreshold=10`, `sigma=1.6`, `CV_32F` × 128 |
| Query processing | 960×720 SIFT; keypoints mapped to native **1920×1440** |
| Offline geometry | COLMAP sparse reconstruction (observations + Point3D XYZ) |
| Reference descriptors | **OpenCV SIFT on native DJI images**, not COLMAP descriptors |
| Association | image-space xy, 2 px, exclusive buckets (`baseline_2px`) |
| Matcher | OpenCV BF L2 KNN (`candidateK=16`) → Swift Point3D grouping / ratio (`0.8` strict `<`) / unique dedup |
| Gate 3C fixture | development fixture only; **not** a Wall Package |
| PnP | EPNP / RANSAC / RefineLM on full correspondences; zeros distortion |
| Tracking after lock | ARKit same-frame camera transform; rolling `T_ARWorld_Wall`; **not** persistent lock |
| Languages | Swift, Objective-C++ bridge, Python (offline only) |

`S_wall_colmap` is **VALIDATED** for the current wall (scale
**3.19764417024824** meters / recon-unit). Matching success is not a
pose. Confirmed `T_opencvCam_colmap` is the confirmation-window last
frame. Gate 4A metric `T_ARWorld_Wall` is SE(3). Gate 4B landmarks
W01–W04 are **FROZEN**. Gate 4B AR physical measurement is **PASS / CLOSED**.
Stage 5 is **OPEN / IN PROGRESS** (opened 2026-08-27). Gate 5A is
**PASS / CLOSED**. First route is **FROZEN** (`route_test_01`). Gate 5B is
**PASS / CLOSED**. Route
package creation is **NOT AUTHORIZED**. Route rendering is
**NOT AUTHORIZED**. Gate 5C is **PASS / CLOSED**. Gate 5D–5E are **NOT STARTED**. Stage 5 is
**NOT PASS**.

---

## What is allowed next

Allowed now:

- Human review of Gate 5C PASS / CLOSED
- Gate 5D only after a later explicit protocol
- Explicit instruction to push for GitHub review (not implied)

Stage 5 remains **OPEN / IN PROGRESS**. Gate 5A is **PASS / CLOSED**.
First route is **FROZEN** (`route_test_01`). Gate 5B is **PASS / CLOSED**.
Gate 5C is **PASS / CLOSED**.
That is **not** production
Wall Package `routes.json` authorization and **not** route-rendering
authorization.

**Not allowed now**

- Creating `routes.json` / a production route package
- DXF in the app bundle
- Route rendering / `renderedRoute = true`
- Gate 5D / 5E without a later explicit protocol
- Reopening `IDENTITY_PROVEN` or WallMetricMeters **PROVEN**
- Unfreezing or replacing `route_test_01`
- Reselecting or replacing frozen W01–W04
- Tuning scale, offset, flip, or production `T` from marker appearance
- Persistent lock / ARAnchor persistence / smoothing / Kalman
- Restoring `T_opencvCam_colmap * inverse(S)` as camera SE(3)
- GPS, compass, or manual Sim(3) as a localization success
- SuperPoint, LightGlue, SuperGlue, hloc, Core ML features, on-device
  Python, or on-device COLMAP
- Declaring Stage 5 PASS or route rendering authorized

---

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

Gate 3C matching currently loads a **development fixture** copied from
`offline/work/…/reference_matching/baseline_2px/`. That is not
`walls/`.

To add a wall:

```text
./rockvision ingest wall_<id>
./rockvision qualify wall_<id>
```

Later Stage 2 tools (already used for the current wall):

```text
./rockvision reconstruct wall_<id>
./rockvision register wall_<id>
```

Details: [incoming/README.md](incoming/README.md).

---

## Documents

| Document | Purpose |
|----------|---------|
| [docs/ROCKVISION_V2_ARCHITECTURE.md](docs/ROCKVISION_V2_ARCHITECTURE.md) | System architecture **definitions** (authoritative unless superseded) |
| [docs/WALL_PACKAGE_SPEC.md](docs/WALL_PACKAGE_SPEC.md) | Versioned Wall Package schema |
| [docs/COORDINATE_CONVENTIONS.md](docs/COORDINATE_CONVENTIONS.md) | Coordinate frames and `T_A_B` **definitions** (authoritative unless superseded) |
| [docs/CAMERA_IMAGE_CONVENTION.md](docs/CAMERA_IMAGE_CONVENTION.md) | ARFrame / SIFT image and keypoint space |
| [docs/OPENCV_IOS_BUILD.md](docs/OPENCV_IOS_BUILD.md) | Pinned OpenCV 4.14.0 xcframework build |
| [docs/DEVELOPMENT_GATES.md](docs/DEVELOPMENT_GATES.md) | Gate discipline; live status at top; Gate 0–11 body is early plan numbering |
| [incoming/README.md](incoming/README.md) | How to add a wall (raw drop) |

**Identified status statements in those docs are stale; definitions are
not.** Stage / Gate / `S_wall_colmap` **current status** is this README.
Only the identified status lines below are outdated. Architecture and
coordinate-convention **definitions** remain authoritative unless a later
decision explicitly supersedes them. Those files are not deprecated and
must not be ignored.

Stale **status** lines (do not treat as live):

- `docs/ROCKVISION_V2_ARCHITECTURE.md` opening: “specification only /
  No Gate 0+ implementation yet”
- `docs/COORDINATE_CONVENTIONS.md` §3.1 historical 2026-08-23 audit:
  reconstruction then had `S_wall_colmap.status = unknown`. **Current**
  wall Sim(3) is **VALIDATED**; Gate 4A metric alignment is
  **PASS / CLOSED**. The Sim(3) **definition** in that section still
  applies.

Coordinate frames, `T_A_B` notation, and the Sim(3) **definition** in
those documents still apply. The Sim(3) **status** for the current wall
is **VALIDATED**, recorded here.

---

## Historical / deprecated approaches

Not the current iPhone production path. Do not implement them.

- V1 SuperPoint / LightGlue / SuperGlue / hloc runtime
- Core ML feature extraction on device
- GPS “preview alignment”
- Manual T/R/S sliders as localization
- Copying COLMAP or SuperPoint descriptors into the Wall Package

If an older doc still discusses those stacks, treat them as **rejected
explorations**, not alternatives.
