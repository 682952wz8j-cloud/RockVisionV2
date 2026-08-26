# Development Gates

Development is sequential. **Never implement multiple gates in one
change.**

For every gate:

```text
Implement
  → Build
  → Unit test where applicable
  → Physical iPhone test where applicable
  → Quantitative logs
  → Report result
  → STOP
```

If a gate fails, fix **that gate only**. Do not modify downstream systems
to compensate. Do not change the technology stack to escape a failed
measurement.

V1 is not a starting branch.

---

## Current position

**Live status source of truth: [`README.md`](../README.md).**

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
Stage 4 — AR Alignment                       IN PROGRESS
  Gate 4A — SAME-FRAME / LIFETIME            PASS / CLOSED
           formal field: gate4a_20260825_104607
  Gate 4A — METRIC ALIGNMENT                 PASS / CLOSED
  Gate 4B                                  diagnostic geometry present;
                                           landmarks FROZEN (W01–W04);
                                           measurement preparation IN PROGRESS;
                                           physical measurement NOT STARTED;
                                           not PASS
Stage 5 — Route AR                           BLOCKED
```

`S_wall_colmap` is **VALIDATED**. Gate 4A production `T_ARWorld_Wall` is
the metric SE(3) product in [`COORDINATE_CONVENTIONS.md`](COORDINATE_CONVENTIONS.md)
§6. That is **not** persistent Wall↔ARWorld lock and **not** permission
to render routes.

Gate 4B Layer 1 diagnostic geometry (origin + 1 m XYZ axes) is present.
Landmarks W01–W04 are **FROZEN** in
[`validation/gate4b/gate4b_landmarks_frozen.json`](../validation/gate4b/gate4b_landmarks_frozen.json).
Measurement preparation is **IN PROGRESS**. Physical measurement has
**not** started. Gate 4B is **not** PASS.

---

## Live numbering

- **Live status source of truth = `README.md`**
- Current numbering: Stages **1–5**; Stage 3 contains Gate **3A–3E**;
  Stage 4 contains Gate **4A / 4B**
- The Gate 0–11 chapters below are the **early plan numbering**
- Live Gate **3C** is reference matching (this document’s historical
  “Gate 4”)
- Live Gate **3D** is PnP (this document’s historical “Gate 6”)
- Live Gate **3E** is multi-frame confirmation (this document’s
  historical “Gate 7”)
- Live Gate **4A** is production `T_ARWorld_Wall` (this document’s
  historical “Gate 8” alignment product)
- Live Gate **4B** is metric Wall-frame validation in ARWorld
- Do **not** treat historical Gate 8 as still blocked on missing pose

---

## Pre-work (completed)

Location: `/Users/zhengzhang/Documents/RockVisionV2`

V1 untouched: `/Users/zhengzhang/Documents/RockVision`

Delivered:

- `docs/ROCKVISION_V2_ARCHITECTURE.md`
- `docs/WALL_PACKAGE_SPEC.md`
- `docs/COORDINATE_CONVENTIONS.md`
- `docs/DEVELOPMENT_GATES.md`
- Proposed directory layout (see architecture §8)
- OpenCV **reproducible** xcframework plan; version **TBD at Gate 3**
- Offline exporter plan (architecture §10)
- Unique-Point3D matching (architecture §9.6)
- COLMAP units vs metric Wall / `S_wall_colmap` (coordinate conventions §3)
- Data stages: `incoming/` → `offline/work/` → `walls/`
- Incoming input-validation requirements
- Uncertainties U1–U9 (architecture §14)

No Xcode project. No exporter code. No Wall Package files.

---

## Gate 0 — Clean project

**Create** a new Xcode iOS app under `ios/` named RockVision.

Verify:

- `xcodebuild` succeeds
- App installs on a **physical iPhone**
- ARKit session starts (`ARWorldTrackingConfiguration`)
- Camera frames arrive
- Debug overlay can show: localization state `idle`, ARKit tracking state

**Do not** add OpenCV, Wall Packages, GPS, or routes.

**STOP.**

---

## Gate 1A — Raw Data Ingestion

Independent offline tool. Input: `wall_<id>`. Recursively scan
`incoming/wall_<id>/` (Raw Drop; do not require `photos/` / `model/` /
`routes/` / `metadata/`). Classify from extension + signature +
lightweight content, never from folder names.

Write only:

```text
offline/work/wall_<id>/ingestion/inventory.json
offline/work/wall_<id>/ingestion/validation_report.md
```

`incoming/` is read-only. Do not modify, rename, or delete source files.
Do not run COLMAP, SIFT, OpenCV, Wall Package export, or iOS work.

Command:

```text
./rockvision ingest wall_<id>
```

Validation result rules are in `offline/ingestion/validate.py`:

- **FAIL**: wall missing / inaccessible; no readable photographs;
  incoming changed during the run
- **PASS**: at least one readable photograph and no warnings
- **PASS WITH WARNINGS**: readable photographs exist, plus non-blocking
  issues (missing metadata, RTK parser not implemented, unknowns,
  duplicates)

Later offline steps must consume `inventory.json`. They must not walk
`incoming/` and guess types again.

**STOP.** Do not start Gate 1 or Gate 2.

---

## Gate 1B — Source Data Qualification

Read-only investigation of `incoming/wall_<id>/` plus Gate 1A
`inventory.json`. Writes only:

```text
offline/work/wall_<id>/qualification/
```

Command:

```text
./rockvision qualify wall_<id>
```

Classify source vs derived images, parse RTK/GNSS that can be parsed,
measure PLY/DXF/tileset coordinate evidence, and emit a provenance
report. Every relationship is PROVEN / SUPPORTED / UNKNOWN /
CONTRADICTED.

Do not run COLMAP, modify incoming, or invent transforms.

**STOP.**

---

## Gate 1 — Wall Package specification

The schema already lives in `WALL_PACKAGE_SPEC.md`.

This gate is **implementation of types + a fixture loader**, not
localization.

- Swift types for manifest, frames, landmarks, routes
- `WallDataProvider` + `BundleWallDataProvider`
- Tests: parse a hand-written **tiny** fixture; reject bad version,
  checksum mismatch, ENU routes without `S_wall_enu`, production
  alignment when `S_wall_colmap.status = unknown`
- No SIFT, no matching, no AR placement

**STOP.**

---

## Gate 2 — Offline COLMAP / OpenCV exporter

Create `offline/exporter/`.

Consume Gate 1A `inventory.json`. Do **not** re-walk `incoming/` and
re-guess file types. If inventory is missing or `FAIL`, stop.

Then:

```text
incoming/wall_<id>/          read-only
  → offline/work/wall_<id>/  COLMAP + OpenCV intermediates
  → OpenCV SIFT on each registered image
  → geometric association to COLMAP observations
  → QA
  → walls/wall_<id>/         Wall Package
```

Must report the statistics listed in the Wall Package spec.

Must **not**:

- use feature indices as correspondence
- copy COLMAP or SuperPoint descriptors into the package
- write ENU routes as metric Wall-frame routes
- label COLMAP `xyz` as meters
- set `S_wall_colmap = I` without a proven Sim(3)
- overwrite, rename, or edit anything under `incoming/`
- write generated files into `incoming/`
- modify files under the V1 tree

Acceptance: validation report + association report; accepted landmarks
have valid `point3DId` and COLMAP XYZ; `S_wall_colmap.status = unknown`
until proven; reviewer can inspect overlays / counts.

**STOP.**

---

## Gate 3 — iPhone OpenCV SIFT

OpenCV version is **TBD until this gate**. Then:

1. verify the then-current stable OpenCV 4.x release;
2. verify Apple `build_xcframework.py` support;
3. verify `features2d` / `cv::SIFT::create()`;
4. verify `calib3d` / `cv::solvePnPRansac()`;
5. select the version;
6. pin exact tag and commit;
7. record the reproducible build (command, archs, modules, SHA-256).

After that pin, the version must not float.

Build with `platforms/apple/build_xcframework.py` (architecture §9.2).
Device `arm64` + simulator `arm64`. No contrib / nonfree / xfeatures2d.

Bridge: `RVImageConverter` + `RVSIFTExtractor` (+ compile-check
`RVPnPSolver` symbols).

On a physical iPhone, verify:

- `cv::SIFT::create()` runs
- `cv::solvePnPRansac()` is linked (may be called on a synthetic fixture)
- stable `ARFrame` acquisition
- documented orientation
- logs: input resolution, processed resolution, feature count, latency

No matching. No package consumption required beyond perhaps ignoring it.

**STOP.**

---

## Gate 4 — Reference matching (unique Point3D)

Load the bundled Wall Package localization DB.

```text
query descriptor
  → OpenCV KNN (raw descriptor rows)
  → map to point3DId
  → group; best distance per Point3D
  → ratio / ambiguity between DISTINCT Point3Ds
  → at most one Point3D per query keypoint
```

Verify (logs / debug draw):

- raw descriptor candidate count
- unique Point3D candidate count
- duplicate-observation collapses
- ratio rejects **after** Point3D grouping
- accepted matches point at plausible regions
- `knnK`, `ratioThreshold` are named config values
- unit test: two reference rows of the same Point3D as 1-NN and 2-NN
  must **not** fail the ratio test for that reason

No PnP. No AR alignment. No Lowe ratio on raw descriptor neighbors.

**STOP.**

---

## Gate 5 — Unique 2D–3D correspondences

Convert accepted Point3D matches to:

```text
unique (u, v)_query  ↔  unique Point3D  ↔  (X, Y, Z)_colmap
```

If several query features selected the same Point3D, keep the
best-quality one and reject the rest.

Log:

- duplicate Point3D rejects before PnP
- final unique 2D–3D count
- a sample of pairs (query uv, point3DId, COLMAP xyz)

XYZ are reconstruction units, not meters.

Do not run PnP. Do not lock AR. Do not call `productionAlignment`.

**STOP.**

---

## Gate 6 — PnP

`cv::solvePnPRansac` with iPhone `K` and **unique** COLMAP XYZ.

Output:

- `T_opencvCam_colmap` (reconstruction units)
- full quality metrics (§ architecture 11.1)

This is the first stage that may be called **Visual Pose Estimation**.

It is **not** a metric AR transform. Do not derive `T_ARWorld_Wall`.
Do not label `t` as meters.

One good frame is **not** `VISUAL_LOCALIZED`.

**STOP.**

---

## Gate 7 — Multi-frame visual localization

Compare consecutive candidate poses (translation, rotation, reprojection,
inliers, inlier ratio).

Only then transition to `localized` / `VISUAL_LOCALIZED`.

Thresholds are named and marked uncalibrated.

**STOP.**

---

## Gate 8 — Coordinate alignment test

**Live equivalent: Gate 4A PASS / CLOSED; Gate 4B diagnostic present,
landmarks FROZEN (W01–W04); physical measurement not started.**

Stage 3 has produced confirmed `T_opencvCam_colmap`. Gate 4A generates
`T_ARWorld_Wall` from that pose, validated `S_wall_colmap`, and the
same-ARFrame ARKit camera transform. The production product is metric
SE(3) (Wall meters → ARWorld meters). See coordinate conventions §6.

Gate 4A is **not** persistent Wall↔ARWorld lock.

Gate 4B Layer 1 diagnostic geometry (Wall origin + 1 m XYZ axes) is
present and consumes production `T_ARWorld_Wall` only. Formal landmarks
W01–W04 are **FROZEN**. Physical landmark measurement has **not**
started. Do **not** treat diagnostic axes as Gate 4B PASS. Do **not**
reselect frozen landmarks.

- Do **not** render climbing routes.
- Do **not** use runtime GPS or T/R/S as a substitute.
- Do **not** use bbox size as proof of meters.
- Do **not** restore `T_opencvCam_colmap * inverse(S_wall_colmap)` as
  the camera SE(3).

If debug axes drift or sit in the wrong place: debug correspondences,
PnP, `K`, `T` direction, `S_wall_colmap` — not a T/R/S slider, and not
an empirical scale in the overlay.

**STOP.** Remaining Gate 4B measurement preparation (independent method)
and physical measurement start only when explicitly opened.

---

## Gate 9 — Single route

Render **one** polyline that is already in Wall Frame.

Verify physical alignment on device.

V1 ENU routes are ineligible until `S_wall_enu` is defined or the
polyline is re-digitized in metric Wall Frame. Also requires
`S_wall_colmap.status = defined`.

**STOP.**

---

## Gate 10 — Multiple routes

Only after Gate 9 succeeds.

**STOP.**

---

## Gate 11 — Relocalization

Visual correction after tracking loss or excessive drift.

Re-run the same OpenCV SIFT → match → PnP → confirm path.
Replace `T_ARWorld_Wall` with a new production alignment.

No GPS fallback pose.

**STOP.**

---

## Gate discipline

| Allowed in a gate | Not allowed |
|-------------------|-------------|
| Fixing that gate’s bugs | Implementing the next gate “while we’re here” |
| Adding logs required by that gate | Adding SuperPoint “just to compare” on device |
| Tightening association / ratio / RANSAC **configs** | Manual route offsets |
| Reporting U1–U9 with numbers | Silent stack change |
| Unit tests for new types | GPS production alignment |

Physical iPhone tests are mandatory from Gate 0 (AR session) and Gate 3
(SIFT) onward. Simulator is insufficient for ARKit + camera + OpenCV
timing.

---

## Mapping product pipeline → gates

```text
incoming/ → inventory.json     Gate 1A
inventory.json → work/ → walls/ Gate 2 (export; consumes inventory)
GPS candidate selection        later catalog work; not required to prove VL
Load Wall Package              Gate 1 (types), Gate 2 (real data)
Visual Localization            Gates 3–6
Multi-frame lock               Gate 7
T_ARWorld_Wall + landmarks     Gate 8 (requires defined S_wall_colmap)
Routes                         Gates 9–10
ARKit tracking                 Gate 8+ (session exists from Gate 0)
Relocalization                 Gate 11
```

---

## After this document

Gate 1A is complete when implemented. **STOP** and wait for review.
Do not start Gate 1, Gate 2, COLMAP, OpenCV iOS, or Visual Localization.
