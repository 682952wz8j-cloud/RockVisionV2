# RockVision V2 Architecture

Status: specification only. No Gate 0+ implementation yet.

V1 at `/Users/zhengzhang/Documents/RockVision` is a **read-only** record of
product requirements and failure modes. V2 does not import V1 source, Xcode
settings, SuperPoint assets, `.rvloc` packs, or GPS-preview alignment.

---

## 1. Product objective

RockVision is an iPhone AR app for outdoor rock climbing.

The climber points the camera at a **known** real-world rock wall. The app
must:

1. Determine the iPhone camera’s **6DoF pose relative to that wall** using
   vision only.
2. Render known climbing route polylines at their **correct physical
   positions** on the wall.
3. After a validated visual lock, follow camera motion with ARKit tracking.
4. Relocalize visually when tracking is lost or drift is excessive.

Visual localization is the product core. UI, social features, and cloud
delivery are deferred until the localization core is proven.

---

## 2. Fixed technology stack

Do not reopen technology selection.

| Layer | Technology | Role |
|-------|------------|------|
| Offline geometry | COLMAP + SIFT | Sparse SfM: cameras, observations, `POINT3D_ID → XYZ` |
| Offline descriptors | OpenCV SIFT | Reference keypoints/descriptors associated to COLMAP 3D |
| Offline language | Python | Exporter and validation only |
| iPhone language | Swift | App, state machine, data, AR, debug UI |
| iPhone vision | OpenCV (iOS) via Objective-C++ | SIFT, matching, PnP |
| Tracking | ARKit | High-frequency camera motion **after** visual lock |
| Rendering | RealityKit (planned Gate 8+) | Landmarks, then routes, in ARWorld |

### One localization implementation

```text
ARFrame
  → OpenCV SIFT
  → OpenCV descriptor candidates (KNN)
  → group by Point3D ID
  → unique-Point3D ranking + ratio / ambiguity test
  → unique query 2D ↔ unique Point3D
  → OpenCV solvePnPRansac
  → pose validation
  → multi-frame confirmation
  → T_opencvCam_colmap
  → (only if S_wall_colmap defined) T_wall_camera / T_ARWorld_Wall
```

### Forbidden on iPhone

- SuperPoint, LightGlue, SuperGlue
- hloc runtime
- Core ML feature extraction
- Python runtime
- COLMAP runtime
- Multiple interchangeable localization pipelines
- `ARReferenceObject` as the wall-recognition path

If a Gate 2–6 result is poor, report it. Do not silently change this stack.

---

## 3. Runtime pipeline

```text
GPS (coarse)
  → Crag / Wall candidate selection
  → Load Wall Package  (Local Cache → Bundle → Remote)
  → Visual Localization
        ARFrame → SIFT → unique-Point3D match → (u,v)↔Point3D → PnP/RANSAC
  → multi-frame confirmation
  → T_opencvCam_colmap
  → S_wall_colmap (Sim(3); required before metric AR)
  → T_ARWorld_Wall
  → render metric wall-space content
  → ARKit tracking
  → visual relocalization when required
```

GPS is finished once a Wall Package is selected. After that, pose is visual.

ARKit answers: *how has the camera moved since lock?*
Visual Localization answers: *where is the camera relative to the known wall?*

---

## 4. GPS boundary

GPS / compass **may**:

- identify the approximate climbing area;
- narrow Wall candidates;
- decide which Wall Package to load.

GPS / compass **must never**:

- determine route screen position;
- determine wall orientation for production alignment;
- generate an AR pose;
- modify a visual pose;
- act as fallback localization;
- cause Visual Localization to report success.

The Visual Localization module **must not import or depend on `CLLocation`**.

Candidate selection lives in a separate module, e.g. `WallCandidateSelector`.
It may read location. It outputs a `wallId`. It does not output a pose.

There is no GPS “preview alignment” in V2 production. If the user is at the
wall but not yet visually localized, the UI may show camera + debug + an
honest “searching / not localized” state. It must not place routes.

---

## 5. Module boundaries

Localization state must not be distributed across ViewControllers, SwiftUI
views, or `ARSession` callbacks. Those layers observe a single store.

```text
App
  Features/
    ARSessionHost          ARKit session only; no pose math
    DebugOverlay           read-only diagnostics; separable from product UI
    ClimbingUI             product chrome; no localization logic
  Domain/
    LocalizationStateMachine
    VisualLocalizer        SIFT → match → PnP → candidate pose
    PoseConfirmer          multi-frame consistency → localized
    Coordinates            the only place axis/basis changes live
    WallPackage            types consumed by VL / routes / rendering
  Data/
    WallDataProvider       protocol
    BundleWallDataProvider current
    CachedWallDataProvider future
    RemoteWallDataProvider future, not implemented
    WallCandidateSelector  GPS coarse only; not a localizer
  Bridge/OpenCV/
    RVSIFTExtractor
    RVDescriptorMatcher
    RVPnPSolver
    RVImageConverter
  Domain/Localization/
    Point3DMatchCollapser  unique Point3D ranking + ratio + PnP dedup
  Rendering/               empty until Gate 8
```

### Dependency direction

```text
Features → Domain / Data / Rendering
VisualLocalizer → WallPackage + OpenCV bridge + Coordinates
PoseConfirmer → candidate poses only
Rendering → WallPackage + T_ARWorld_Wall
WallCandidateSelector → location + wall catalog
VisualLocalizer ↛ CLLocation
Rendering ↛ GPS
Features ↛ OpenCV C++ headers
```

---

## 6. Localization state machine

Owned by one type, e.g. `LocalizationStateMachine`.

```text
idle
  → wallKnown
  → loadingWallPackage
  → ready
  → searching
  → matching
  → solvingPose
  → candidatePose
  → confirming
  → localized
  → tracking
  → relocalizing
  → failed
```

| State | Meaning |
|-------|---------|
| `idle` | No wall selected |
| `wallKnown` | `wallId` chosen; package not loaded |
| `loadingWallPackage` | Provider fetching package |
| `ready` | Package in memory; not searching yet |
| `searching` | Extracting query SIFT |
| `matching` | Descriptor matching |
| `solvingPose` | PnP/RANSAC running |
| `candidatePose` | One frame produced a quantitative pose (not a lock) |
| `confirming` | Comparing consecutive candidate poses |
| `localized` | Multi-frame confirmation passed. First legal `VISUAL_LOCALIZED` |
| `tracking` | ARKit holding `T_ARWorld_Wall` |
| `relocalizing` | Visual correction after loss / drift |
| `failed` | Recoverable or terminal failure with a reason |

A single PnP success is **never** `localized`.

Every transition records diagnostics (see §12). Success/fail booleans are
derived views, not the stored result.

---

## 7. Wall data

There is no production server.

Current source: **App Bundle**.

Resolution order (implement Bundle now; leave the others as empty types or
comments until needed):

```text
Local Cache → Bundle → Remote
```

Protocol:

```text
WallDataProvider
  func loadPackage(wallId: String) throws -> WallPackage
```

Current implementation: `BundleWallDataProvider`.

Visual Localization, Coordinates, PnP, and AR Rendering consume **only**
`WallPackage`. They do not know whether it came from bundle, cache, or
network.

Schema: [WALL_PACKAGE_SPEC.md](WALL_PACKAGE_SPEC.md).

### Existing test wall (V1 record, not copied)

| Field | Value |
|-------|--------|
| Wall ID | `wall_jiulongfeng_01` |
| Site | 九龙峰森林站大楼 (Jiulongfeng) |
| WGS84 (catalog only) | 30.129955°N, 118.014989°E, ~315 m |
| Reference images | 63 DJI JPG, 5280×3956 |
| COLMAP SIFT reconstruction | 62 registered images, 53 472 points, 211 827 3D observations |
| COLMAP camera | `SIMPLE_RADIAL`, f≈3681.62, cx=2640, cy=1978, k≈−0.1104 |
| Routes in V1 | 3 DXF polylines in `local_enu_east_up_north_meters` |

V1 also has a SuperPoint reconstruction and `.rvloc` pack. **V2 must not
use them.** V2 localization data is regenerated by the Gate 2 exporter from
the COLMAP SIFT reconstruction + OpenCV SIFT on the same reference JPGs.

V1 paths remain a **historical record**. New walls, and any copy of
Jiulongfeng source files intended for V2, go under `incoming/` only.
Do not modify the V1 tree.

---

## 8. Repository layout and data stages

```text
incoming/wall_<id>/          raw drop (immutable originals)
        ↓
Raw Data Ingestion           inventory.json (Gate 1A)
        ↓
offline/work/wall_<id>/      generated intermediates
        ↓
QA / Geometry Registration
        ↓
walls/wall_<id>/             validated Wall Package
        ↓
WallDataProvider             Bundle → (later) Cache → Remote
        ↓
iPhone
```

Future cloud (same Wall Package, same VL algorithm):

```text
walls/wall_<id>/  →  Cloud Storage  →  RemoteWallDataProvider  →  Local Cache  →  iPhone
```

| Stage | Path | Who writes | Consumed by |
|-------|------|------------|-------------|
| Raw | `incoming/wall_<id>/` | Chairman only | Gate 1A ingestion |
| Work | `offline/work/wall_<id>/` | Offline pipeline | Exporter / QA |
| Package | `walls/wall_<id>/` | Offline pipeline after QA | `WallDataProvider` |

`incoming/` is the **only** place the Chairman should put raw wall data.

```text
incoming/wall_<id>/
  <any original export folders and files>
```

Users drop complete device / software exports. They do not classify
files into photos / model / routes / metadata. Ingestion scans
recursively and writes `offline/work/wall_<id>/ingestion/inventory.json`.
Later pipeline stages consume that inventory. They do not re-walk
`incoming/` to guess types.

Pipeline code must **never**:

- overwrite, rename, or edit files under `incoming/`;
- modify EXIF, models, or route sources;
- write COLMAP / OpenCV / Wall Package output into `incoming/`.

`offline/work/` is reproducible and may be deleted. `walls/` is the only
package tree `BundleWallDataProvider` (and later cache/remote) may load.

### Incoming input validation

Gate 1A (`./rockvision ingest wall_<id>`) scans `incoming/wall_<id>/`
and writes:

- `offline/work/wall_<id>/ingestion/inventory.json`
- `offline/work/wall_<id>/ingestion/validation_report.md`

Unsupported or unknown files are listed, not deleted or ignored.
If the report is `FAIL`, later processing must stop.

### Proposed tree

```text
RockVisionV2/
  README.md
  incoming/
    README.md
    wall_jiulongfeng_01/
      <raw device / software export folders>
  docs/
    ROCKVISION_V2_ARCHITECTURE.md
    WALL_PACKAGE_SPEC.md
    COORDINATE_CONVENTIONS.md
    DEVELOPMENT_GATES.md
  ios/                                 # Gate 0 creates the Xcode project here
    RockVision.xcodeproj               # not created yet
    RockVision/
      App/
      Domain/
        Coordinates/
        Localization/
        StateMachine/
        WallPackage/
        Route/
      Data/
        Providers/
        Catalog/
      Bridge/
        OpenCV/                        # ObjC++ only
      Features/
        ARSessionHost/
        DebugOverlay/
        ClimbingUI/
      Rendering/
      Resources/
        Walls/                         # copies of walls/ packages for the bundle
    RockVisionTests/
      Coordinates/
      Localization/
      WallPackage/
    Vendor/
      OpenCV/                          # reproducible xcframework at Gate 3
        VERSION.txt                    # tag, commit, command, SHA-256 (chosen at Gate 3)
  offline/
    requirements.txt
    exporter/                          # Python package, created at Gate 2
    testdata/
    work/                              # generated; gitignored
      wall_<id>/
  walls/                               # validated Wall Packages only
    wall_<id>/
```

Rules:

- iPhone code never lives under `offline/` or `incoming/`.
- Python never lives under `ios/`.
- Coordinate math has one Swift module plus matching Python helpers used
  only to generate test fixtures.
- Do not add a second localization folder “for later algorithms”.

---

## 9. OpenCV iOS integration

This is the only on-device vision library.

### 9.1 What the app may call

Four Objective-C++ facades. Swift sees only these:

| Facade | Responsibility |
|--------|----------------|
| `RVImageConverter` | `CVPixelBuffer` → grayscale `cv::Mat`; records input/processed size; applies **explicit** orientation + intrinsic updates |
| `RVSIFTExtractor` | `cv::SIFT::create(...)` → keypoints + 128-D descriptors; latency; feature count |
| `RVDescriptorMatcher` | descriptor KNN only; returns raw `(queryIndex, referenceIndex, distance)` |
| `Point3DMatchCollapser` | Swift: group by `point3DId`, ratio on **distinct** Point3Ds, unique 2D–3D |
| `RVPnPSolver` | `cv::solvePnPRansac` → rvec, tvec, inliers, reprojection error |

Swift converts rvec/tvec into `T_wall_camera` using
[COORDINATE_CONVENTIONS.md](COORDINATE_CONVENTIONS.md). The bridge must
document OpenCV’s `X_cam = R * X_world + t` convention and must not invert
it silently.

### 9.2 How OpenCV is obtained (reproducible build)

Do **not** assume a prebuilt official XCFramework contains the required
modules. Do **not** use CocoaPods as the primary path.

**Required method:** official Apple XCFramework tooling. Version is
**TBD at Gate 3**. Do not lock a release number in this specification.

At Gate 3:

1. Verify the then-current **stable** OpenCV 4.x release.
2. Verify `platforms/apple/build_xcframework.py` support.
3. Verify `features2d` / `cv::SIFT::create()`.
4. Verify `calib3d` / `cv::solvePnPRansac()`.
5. Select that version.
6. Pin the **exact tag and commit**.
7. Record the reproducible build.

After selection, the version must **not** float automatically.

| Item | Value until Gate 3 |
|------|---------------------|
| Source | `https://github.com/opencv/opencv` |
| Version / tag | **TBD at Gate 3** |
| Commit | record after the tag is chosen |
| Tool | `platforms/apple/build_xcframework.py` |
| Device | `arm64` |
| Simulator | `arm64` |
| Contrib / nonfree | **off** |
| Required modules | `core`, `imgproc`, `features2d`, `calib3d` |

```text
# TAG is chosen at Gate 3, then frozen.
git clone --branch <TAG> --depth 1 https://github.com/opencv/opencv.git
git -C opencv rev-parse HEAD > ios/Vendor/OpenCV/SOURCE_COMMIT.txt

python3 opencv/platforms/apple/build_xcframework.py \
  --out ios/Vendor/OpenCV/build \
  --iphoneos_archs arm64 \
  --iphonesimulator_archs arm64 \
  --build_only_specified_archs
```

Do **not** pass `--contrib` or `--enable_nonfree`. SIFT lives in main
`features2d` since OpenCV 4.4 (patent expired). Do not enable
`xfeatures2d`.

After the Gate 3 build:

1. Copy `opencv2.xcframework` to `ios/Vendor/OpenCV/`.
2. Write `ios/Vendor/OpenCV/VERSION.txt` with: tag, source commit,
   exact command, architectures, enabled modules, builder machine OS /
   Xcode version.
3. Archive the xcframework (zip) and record **SHA-256** of that archive
   in `VERSION.txt`.
4. On a **physical iPhone**, link and verify `cv::SIFT::create()` and
   `cv::solvePnPRansac()` are available and run.

If the pin must later change, rebuild from the new tag and replace the
VERSION / SHA-256 record. Do not mix leftover binaries from another tag.

### 9.3 Xcode linkage (Gate 3)

1. Add `opencv2.xcframework` to the app target.
2. Link `libc++`, `Accelerate`, `CoreVideo`, `CoreMedia`, `UIKit`.
3. Enable C++ in the target (`C++17` or the OpenCV default).
4. Create an Objective-C++ target membership for `Bridge/OpenCV/*.mm`.
5. Expose the facades through a bridging header **or** an explicit module
   map. Swift files must not `#include <opencv2/...>`.
6. Confirm on a **physical iPhone** that `cv::SIFT::create()` and
   `cv::solvePnPRansac()` run.

### 9.4 SIFT parameters

Offline exporter and iPhone **must use the same named parameter set**.
The names are part of the Wall Package (`localization.sift` in the spec).

Initial values (configurable, not magic numbers buried in code):

| Parameter | Initial value | Notes |
|-----------|---------------|--------|
| `nfeatures` | `0` (OpenCV default = unlimited) | iPhone may cap after extract for latency |
| `nOctaveLayers` | `3` | OpenCV default |
| `contrastThreshold` | `0.04` | OpenCV default |
| `edgeThreshold` | `10` | OpenCV default |
| `sigma` | `1.6` | OpenCV default |
| `descriptorType` | `float32` | 128-D; stored as such in the package |

If Gate 3 latency is too high, lower processed resolution or cap
`nfeatures` **and** re-run the exporter with the same cap/scale policy.
Do not retune only one side.

### 9.5 Frame orientation and intrinsics

`ARFrame.capturedImage` is typically a landscape `CVPixelBuffer`.
`ARCamera.intrinsics` is in that buffer’s pixel space.

Rules:

- Extract SIFT in a documented buffer orientation.
- If the buffer is rotated or mirrored to “upright,” apply the same
  2D transform to keypoints **and** to `fx, fy, cx, cy`.
- Do not resize/crop without scaling/shifting `K`.
- Record `inputWidth/Height`, `processedWidth/Height`, feature count,
  extract latency.

Distortion on the query iPhone is treated as **zero unless ARKit provides
a model**. Do not copy the DJI `SIMPLE_RADIAL` `k` into the iPhone PnP.

### 9.6 Matching (unique Point3D, not raw descriptor rows)

A COLMAP Point3D may have **several** OpenCV reference descriptors
(one per associated observation). Flat-row Lowe ratio is wrong:

```text
descriptor A → Point3D 100
descriptor B → Point3D 100
query nearest = A, second = B   →  ratio test rejects a correct landmark
```

It also feeds duplicate object points into PnP.

**Matching unit = unique `point3DId`.**

```text
query descriptor
  → OpenCV KNN against reference descriptor rows
  → map each candidate to point3DId
  → group by point3DId; keep the best descriptor distance per Point3D
  → rank distinct Point3Ds by that best distance
  → ambiguity / ratio test between DIFFERENT Point3Ds
  → accept at most one Point3D per query keypoint
  → before PnP: at most one query observation per Point3D
       (if several query features pick the same Point3D, keep the best)
  → unique (u,v) ↔ unique Point3D XYZ
```

Configurable:

| Name | Initial value | Meaning |
|------|---------------|---------|
| `knnK` | `8` | Descriptor neighbors **before** Point3D grouping. Must be > 2 so two rows of the same Point3D do not consume the whole list |
| `ratioThreshold` | `0.8` | Accept if `d_bestPoint3D / d_secondPoint3D < ratio`. Calibrate later |
| `minDistinctPoint3DForRatio` | `2` | If grouping yields only one Point3D, reject (cannot test ambiguity) |
| `maxDescriptorDistance` | unset | Optional hard cap; off until measured |

OpenCV’s matcher returns raw descriptor pairs only. Grouping, ratio, and
dedup are Swift (`Point3DMatchCollapser`), so the rule stays testable
without C++.

Output of every **accepted** match (after collapse):

```text
queryKeypointIndex
bestReferenceFeatureIndex
bestDistance
point3DID
xyzColmap
```

Required diagnostics (every frame):

| Count | Meaning |
|-------|---------|
| raw descriptor candidates | KNN rows before grouping |
| unique Point3D candidates | distinct IDs after grouping |
| duplicate-observation collapses | extra descriptor rows dropped per Point3D |
| ratio rejects after Point3D grouping | failed distinct-Point3D ratio |
| duplicate Point3D rejects before PnP | extra query features sharing a Point3D |
| final unique 2D–3D count | PnP input size |

Do not run Lowe ratio on raw descriptor neighbors.
Do not pass duplicate `point3DId` rows into `solvePnPRansac`.

Reference storage may remain a flat descriptor table. The **algorithm**
must still group by Point3D. Per-image retrieval can be added later
without changing that rule.

### 9.7 PnP

```text
cv::solvePnPRansac(
  objectPoints,      // unique Point3D XYZ (COLMAP units in Gates 2–6)
  imagePoints,       // unique query (u,v) in the processed image
  cameraMatrix,      // iPhone K after the same transform as keypoints
  distCoeffs,        // zeros unless a real iPhone model exists
  rvec, tvec,
  /* useExtrinsicGuess */ false,
  iterationsCount,   // configurable
  reprojectionError, // configurable, pixels
  confidence,        // configurable
  inliers,
  flags              // SOLVEPNP_ITERATIVE or SOLVEPNP_EPNP; documented
)
```

This is the first stage that may be called **Visual Pose Estimation**.

---

## 10. Offline COLMAP / OpenCV exporter

Created at Gate 2. Python.

Canonical inputs: Gate 1A `offline/work/wall_<id>/ingestion/inventory.json`
(source files remain under `incoming/wall_<id>/`, read-only).

Writes **only** under:

- `offline/work/wall_<id>/` — COLMAP DB, sparse model, OpenCV features,
  association overlays, validation reports
- `walls/wall_<id>/` — validated Wall Package after QA

Never write into `incoming/`. Never modify V1.

### 10.1 Inputs

| Input | Path | Use |
|-------|------|-----|
| Inventory | `offline/work/wall_<id>/ingestion/inventory.json` | Formal file list and types |
| Reference photographs | inventory `image` records | COLMAP + OpenCV SIFT |
| Optional 3D model | inventory `model3D` records | QA / registration / optional visual payload |
| Raw routes | inventory `routeGeometry` records | Converted later into Wall-frame polylines |
| RTK / GNSS | inventory `rtkGnss` records | Future metric Sim(3); not discarded |
| Optional notes | inventory `structuredData` / `metadata` | Catalog fields if present |

A previous COLMAP reconstruction may be **copied** into
`offline/work/` as a starting point. It is not an `incoming/` file and
must not be written back to `incoming/`.

V1 SuperPoint / `.rvloc` / hloc outputs are not inputs.

### 10.2 Why OpenCV SIFT is re-extracted

COLMAP and OpenCV SIFT are different implementations (normalization,
quantization, detection). The COLMAP database stores 128-D descriptors
(`descriptors.cols == 128`) but they must **not** be shipped as OpenCV
query-side references.

COLMAP’s job: `observation → POINT3D_ID → XYZ`.

OpenCV’s job: descriptors that the iPhone can match.

### 10.3 Association (must not use feature indices)

COLMAP `images.bin` `points2D` and a fresh OpenCV SIFT run are **not**
index-aligned. On the existing reconstruction, COLMAP database keypoint
rows and reconstruction `points2D` counts already differ per image
(example: 14 937 DB keypoints vs 14 300 `points2D` on one image). Index
equality is false.

For each registered reference image:

1. Load the JPG at native resolution (5280×3956). Do not silently resize.
2. Run OpenCV SIFT with the frozen parameter set.
3. Collect COLMAP observations with a **valid** `POINT3D_ID` (not
   `kInvalidPoint3DId`). Each is `(x, y, point3D_id, xyz)`.
4. COLMAP `xy` is in the reconstruction’s image coordinate convention
   (pixel origin top-left; values are subpixel). Use those `xy` as the
   observation locations. Do not “fix” them with undocumented +0.5
   hacks unless a measured convention mismatch is documented and tested.
5. Associate each OpenCV keypoint to at most one observation:

   - Primary: image-space distance.
   - Optional gates: scale ratio, orientation difference, if both sides
     have a reliable scale/angle.
   - Mutual nearest neighbor in image space.
   - Reject if the second-nearest observation is too close
     (ambiguity radius / uniqueness ratio — configurable).
   - Reject if two OpenCV features claim the same observation.
   - Reject features with no 3D id.

6. Do **not** use descriptor distance between COLMAP SIFT and OpenCV
   SIFT as the association signal. That would mix implementations.

7. Do **not** force every OpenCV feature to get a 3D point.

### 10.4 Output

A Wall Package localization database whose records are equivalent to:

```text
referenceImageID
referenceKeypoint          (x, y, size, angle, octave)
OpenCV descriptor[128]
point3DID                  (original COLMAP id, preserved)
xyz                        (COLMAP reconstruction units; not meters)
```

Plus `association_report.json`:

| Statistic | Required |
|-----------|----------|
| COLMAP registered images | yes |
| COLMAP 3D observations | yes |
| OpenCV SIFT features (per image and total) | yes |
| Candidate associations (within radius) | yes |
| Accepted 3D-associated features | yes |
| Rejected: no neighbor / ambiguous / non-mutual / no 3D | yes |
| Usable landmark percentage | yes |
| SIFT parameters used | yes |
| Image sizes | yes |

### 10.5 COLMAP units vs metric Wall (Gate 2–6 vs Gate 8)

Jiulongfeng COLMAP is **not proven metric**. See coordinate conventions
§3.1. Package field:

```text
S_wall_colmap.status = unknown
```

Gates 2–6:

- landmarks and PnP use **COLMAP reconstruction XYZ**;
- output is `T_opencvCam_colmap` in reconstruction units;
- **must not** be interpreted as a metric AR transform;
- **must not** call `productionAlignment`.

Gate 8+ is blocked until an offline Sim(3) `S_wall_colmap` is solved
and recorded (scale, rotation, translation). Then:

```text
X_wall_meters = S_wall_colmap * X_colmap
```

V1 routes live in Terra ENU, which is neither COLMAP nor metric Wall
until `S_wall_enu` is defined. They must not be treated as Wall XYZ.

---

## 11. Pose quality and confirmation

### 11.1 Every PnP attempt logs

- total query features
- raw descriptor candidates
- unique Point3D candidates
- duplicate-observation collapses
- ratio rejects after Point3D grouping
- duplicate Point3D rejects before PnP
- final unique 2D–3D correspondences
- PnP inliers
- inlier ratio
- median / mean reprojection error (inliers)
- translation (`t` in COLMAP units until `S_wall_colmap` is defined)
- rotation (as matrix and as angle-axis)
- processing latency (extract / match / PnP / total)
- accept / reject reason

Do not reduce the stored result to `success` / `failed`.

### 11.2 Multi-frame confirmation

Frames A, B, C, … each produce a candidate `T_wall_camera` if PnP is
internally valid.

Compare:

- translation consistency
- rotation consistency
- reprojection error
- inlier count
- inlier ratio

Only a configurable consistent set may enter `localized`.

**Do not invent production thresholds now.** Ship named fields with
conservative development defaults and mark them `uncalibrated`.

---

## 12. Debug overlay

A separate feature module. Production UI must compile without it.

Required fields (fill as gates land):

| Field | First gate |
|-------|------------|
| Localization state | 0 / 16 |
| Wall ID | 1 |
| SIFT feature count | 3 |
| Raw descriptor candidates / unique Point3D candidates | 4 |
| Duplicate collapses / Point3D-ratio rejects | 4 |
| Final unique 2D–3D count / pre-PnP Point3D dedup | 5 |
| PnP inliers / inlier ratio / reprojection error | 6 |
| Candidate pose count / confidence | 7 |
| ARKit tracking state | 0 |
| Processing latency | 3+ |

---

## 13. V1 failure modes that must not recur

| # | V1 failure | V2 control |
|---|------------|------------|
| 1 | GPS participated in precise alignment (preview `T` could place routes) | No production GPS pose. VL has no `CLLocation`. Routes hidden until `localized` |
| 2 | Success reported without a visual 6DoF pose | `localized` only after confirmed PnP. Diagnostics required |
| 3 | hloc research stack pushed toward the phone | Forbidden list; one OpenCV pipeline |
| 4 | SuperPoint load treated as proof | Feature count ≠ localization. Lock requires correspondences + PnP + confirmation |
| 5 | Routes shown before validated VL | Rendering gated on `localized` / `tracking` |
| 6 | Undefined / pending COLMAP↔geometry frame; COLMAP labeled as meters | Named COLMAP vs metric Wall; `S_wall_colmap` explicit Sim(3); Gate 8 blocked while unknown |
| 7 | Manual T/R/S to hide error | No production T/R/S. No per-site offsets |
| 8 | Several localization subsystems changed at once | One gate at a time |
| 9 | Weak quantitative metrics | Mandatory PnP diagnostics |
| 10 | Single-frame lock | Confirmation state |
| 11 | ARKit tracking confused with wall recognition | ARKit starts after visual lock |
| 12 | Product UI ahead of core | Gates 0–7 before routes; 8 before landmarks-in-AR; 9 before one route |

---

## 14. Technical uncertainties (do not “solve” by changing the stack)

These can stall Gates 2–6. They are reported, not papered over.

### U1 — Aerial references vs ground iPhone queries (highest product risk)

Reference images are DJI aerial / oblique 5K frames. Existing iPhone
queries are ground-level 1024×768 photos.

V1 SuperPoint + LightGlue localized those 3 queries offline (204–633
inliers). That result **does not transfer** to OpenCV SIFT + ratio test.

If Gate 4–6 matching/PnP fails on the same queries, the correct response
is:

- publish quantitative logs;
- stay on OpenCV SIFT;
- consider **data** changes only: add ground-level reference images to a
  **new offline COLMAP reconstruction**, then re-export.

Do not introduce SuperPoint to “make it work”.

### U2 — OpenCV SIFT ↔ COLMAP observation yield

Association is geometric, not index-based. If accepted landmarks are a
tiny fraction of OpenCV features, Gate 2 must still pass as long as the
statistics are honest and the remaining set is usable. If the set is too
sparse for PnP, tune association radii / uniqueness — do not invent 3D
from the mesh.

### U3 — OpenCV iOS binary contents

Resolved as process, not as a stack change: **do not use an unverified
prebuilt XCFramework.** OpenCV version is **TBD at Gate 3**. Gate 3
selects the then-current stable 4.x release, verifies Apple XCFramework
build support, `cv::SIFT::create()`, and `cv::solvePnPRansac()` on a
physical iPhone, then pins tag + commit + SHA-256.

If that tag’s `features2d` unexpectedly omits SIFT, choose another
verified **4.x** tag with the same official script. Do not enable
`xfeatures2d` / nonfree. After the pin, the version must not float.

### U4 — COLMAP pixel convention vs OpenCV keypoint (`x`, `y`)

COLMAP `Point2D.xy` is subpixel. Some pipelines treat COLMAP as
pixel-center (+0.5). A 0.5 px bias is usually harmless at 5280 px; a
wrong axis or origin is not.

Gate 2 must print overlay diagnostics (optional debug image): OpenCV
keypoints vs COLMAP observations. If a systematic shift appears, document
and apply **one** named correction in the exporter.

### U5 — Matching scale on device

~53k 3D points and ~212k observations. After association the landmark
count is unknown. Brute-force L2 against tens of thousands of 128-D
descriptors may exceed a comfortable frame budget.

Still OpenCV: `BFMatcher` first; `FlannBasedMatcher` if measured too
slow. Landmark culling by track length / reprojection is allowed. A
neural retriever is not.

### U6 — Query intrinsics and distortion

PnP is only as good as `K`. ARKit `intrinsics` must be paired with the
exact buffer used for SIFT. Using COLMAP’s DJI `SIMPLE_RADIAL` on the
iPhone is wrong.

iPhone distortion is assumed zero until measured. If reprojection is
biased after otherwise healthy inliers, measure distortion — do not add
a manual route offset.

### U7 — `solvePnPRansac` flag / sample count

Need enough correspondences (far more than 4 in practice on a textured
wall). Flag (`ITERATIVE` vs `EPNP`) and RANSAC pixel threshold will be
calibrated. Wrong `T` direction is a convention bug, not a reason to
hand-tune routes. Tests in [COORDINATE_CONVENTIONS.md](COORDINATE_CONVENTIONS.md)
must lock the multiply order **before** Gate 8.

### U8 — Metric Wall vs COLMAP vs V1 ENU

Two missing Sim(3)s, both `status = unknown`:

| Transform | From → to | Blocks |
|-----------|-----------|--------|
| `S_wall_colmap` | COLMAP units → metric Wall meters | Gate 8 production AR |
| `S_wall_enu` | V1 ENU meters → metric Wall meters | Gates 9–10 if routes stay in ENU |

Jiulongfeng COLMAP was incremental SfM only. GPS EXIF was stored in
`pose_priors` and **not** applied (`use_prior_position = false`). No
`model_aligner`. Pairwise GPS / COLMAP camera-center ratios are ~9.7 —
evidence against “already meters,” **not** a production scale.

Gates 2–6 still run in COLMAP units. They must not emit
`T_ARWorld_Wall`.

Do not use GPS, bbox size, or a visual T/R/S slider to invent either
transform.

### U9 — SIFT parameter / scale parity

If the exporter extracts at 5280×3956 and the phone extracts at ~1920×1440,
SIFT is scale-invariant in theory, but octave coverage and `nfeatures`
caps can still diverge. Gate 2 should also export a **downscaled-reference
experiment** only as a report, or freeze a shared processed-width policy
before Gate 4. Changing only one side is a defect.

---

## 15. Explicit non-goals for this phase

- Backend / Remote provider implementation
- Downloading visual meshes
- SuperPoint / hloc / Core ML
- GPS preview alignment
- Climbing social features
- Implementing more than the currently assigned gate
- Creating the Xcode project before Gate 0 is requested
