# Coordinate Conventions

Status: binding for all V2 code. Every axis change must cite this file.

V1 failed in part because COLMAP, Terra ENU, OpenCV, and ARKit frames were
combined without a finished registration, and because production placement
could be patched by hand. V2 forbids both.

---

## 1. Transform convention

One notation everywhere, Swift and Python:

```text
T_A_B
```

means: **transform a point expressed in coordinate system B into
coordinate system A**.

```text
p_A = T_A_B * p_B
```

Points are column 4-vectors `[x, y, z, 1]`. Matrices are 4×4.

Composition:

```text
T_A_C = T_A_B * T_B_C
```

Inverse:

```text
T_B_A = inverse(T_A_B)
```

Do not invent `T_from_to` aliases. If a library uses another convention
(OpenCV rvec/tvec, ARKit camera-to-world), convert at the boundary in
`Domain/Coordinates` and name the result `T_A_B`.

Similarity transforms (scale + rotation + translation) use:

```text
S_A_B ∈ Sim(3)
X_A = s * R * X_B + t
```

as a 4×4:

```text
S_A_B = | s R   t |
        |  0    1 |
```

`T_A_B` is rigid (scale ≡ 1). Do not write `T_wall_colmap = I` to pretend
COLMAP units are meters.

---

## 2. Named frames

| ID | Role | Handedness | +X | +Y | +Z | Units |
|----|------|------------|----|----|----|-------|
| `colmap_reconstruction_rhs_opencv_units` | Raw COLMAP / SfM world | Right | COLMAP X | COLMAP Y | COLMAP Z | **arbitrary reconstruction units** |
| `wall_metric_rhs_opencv_meters` | **Metric Wall Frame** (production) | Right | Wall X | Wall Y | Wall Z | **meters** |
| `legacy_enu_east_up_north_meters` | V1 Terra / DXF routes | Ordered E,U,N (left-handed as a basis) | East | Up | North | m |
| `opencv_camera_ydown_zfwd` | OpenCV / COLMAP camera | Right | right | **down** | **forward** | same as the world frame used for that pose |
| `arkit_camera_yup_minus_z` | ARKit `ARCamera` | Right | right | **up** | **−forward** | m |
| `arkit_world_gravity_heading_eus` | ARKit / RealityKit world when `worldAlignment = .gravityAndHeading` | Right | East | Up | South | m |
| `realitykit_entity` | RealityKit entity local | Right | same parent-relative convention as RealityKit | | | m |

`opencv_camera_ydown_zfwd` is a **basis**, not a unit system. A pose
`T_opencvCam_colmap` is in reconstruction units. The production camera
pose `T_opencvCamMeters_wall` exists only after `S_wall_colmap` is
defined; it is SE(3) in **meters**. Do not form it as
`T_opencvCam_colmap * inverse(S_wall_colmap)` — that product keeps
reconstruction units on the camera translation.

Image pixels (query and reference):

| Property | Value |
|----------|--------|
| Origin | top-left |
| +u | right |
| +v | down |
| Units | pixels |

There is no “screen frame” for stored geometry.

---

## 3. COLMAP Frame vs Metric Wall Frame

These are **not** the same frame.

```text
X_colmap          raw SfM coordinates (reconstruction units)
       ↓
S_wall_colmap     Sim(3): scale, rotation, translation
       ↓
X_wall_meters = S_wall_colmap * X_colmap
```

| Frame | May be used for | Must not be used for |
|-------|-----------------|----------------------|
| COLMAP reconstruction | Gate 2–6 pose-estimation tests (`T_opencvCam_colmap`) | Production AR meters, route lengths, `T_ARWorld_Wall` |
| Metric Wall Frame | Production landmarks, routes, Gate 8+ AR | Anything, until `S_wall_colmap.status = defined` |

A standard incremental SfM model is defined only up to Sim(3). Labeling
raw COLMAP XYZ as meters is invalid unless metric scale has been
**proven** (GPS-prior mapping with `use_prior_position`,
`model_aligner` / geo-registration, known baseline, or equivalent).

Do **not** infer meters from bounding-box size.

### 3.1 Jiulongfeng audit (2026-08-23)

**Finding: the existing reconstruction is not proven metric. `S_wall_colmap.status = unknown`.**

How it was created (`run_colmap_sfm.py`, pycolmap / COLMAP 3.13.0):

```text
extract_features → match_exhaustive → incremental_mapping → write sfm/
```

| Check | Result |
|-------|--------|
| GPS EXIF read into `pose_priors` | Yes (63 images, WGS84, `coordinate_system = 0`) |
| `use_prior_position` | Default **false**; script never enabled it |
| `model_aligner` / geo-registration | **Not run** |
| Known metric baseline applied | **No** |
| Focal-length EXIF prior | Yes (`3659.40px`) — this is **not** a metric Sim(3) |

Pairwise DJI GPS baselines versus COLMAP camera-center distances (same
image pairs, GPS baseline > 8 m, 1815 pairs) have
`gps_meters / colmap_units` median ≈ **9.74** (min 8.96, max 10.62).
That is evidence **against** “COLMAP units already are meters.” It is
**not** a production scale factor. Do not set `s = 9.74` from GPS.
GPS remains catalog-only.

Until an explicit offline Sim(3) is solved and recorded:

```text
S_wall_colmap.status = unknown
```

That was the 2026-08-23 finding. It is **historical**. The current wall
now has `S_wall_colmap.status = VALIDATED` (see README). Gate 4A
production alignment is **PASS / CLOSED** using the metric SE(3) product
in §6. Gates 2–6 still estimate `T_opencvCam_colmap` in reconstruction
units; that result is not itself `T_ARWorld_Wall`.

### 3.2 Production Wall Frame

The production Wall Frame **must be metric**.

Production route polylines and Gate 8+ test landmarks live only in
`wall_metric_rhs_opencv_meters`.

V1 routes in `local_enu_east_up_north_meters` are not Wall Frame.
`S_wall_enu` (or `T_wall_enu` if already metric ENU) is unknown.
Identity must not be used.

GPS WGS84 is a catalog attribute. It is not a pose, not a Sim(3), and
not a frame for polylines.

---

## 4. OpenCV / PnP pose

`cv::solvePnPRansac` returns `rvec`, `tvec` such that:

```text
X_cam = R * X_world + t
```

Gates 2–6 world is the **COLMAP reconstruction frame**:

```text
R, t  →  T_opencvCam_colmap

T_opencvCam_colmap = | R  t |
                     | 0  1 |
```

`t` is in reconstruction units, not meters.

`inverse(S_wall_colmap)` is the Sim(3) **point-map** inverse:

```text
X_colmap = R_sᵀ (X_wall - t_s) / s
```

It includes scale `1/s` (meters → recon-unit). That inverse is valid for
points. It is **not** a camera SE(3).

OpenCV camera coordinates must be converted to meters **before** they
are composed with ARKit:

```text
X_cam_recon = R_p X_colmap + t_p
X_cam_m     = s * X_cam_recon

R_cam_wall = R_p R_sᵀ
t_cam_wall = s * t_p - R_p R_sᵀ t_s

T_opencvCamMeters_wall = | R_cam_wall  t_cam_wall |
                         | 0           1          |
```

`s` is meters / recon-unit. `s * t_p` is meters. Do **not** use

```text
T_opencvCam_colmap * inverse(S_wall_colmap)
```

as the camera rigid transform. That leftover product maps Wall meters
into camera reconstruction units (linear scale `1/s`) and must not
re-enter `productionAlignment`.

```text
T_wall_opencvCam = inverse(T_opencvCamMeters_wall)
```

The production name `T_wall_camera` means `T_wall_opencvCam` (or the
ARKit-basis equivalent in §6). It **does not exist** while
`S_wall_colmap.status = unknown`.

**Do not guess the direction.** Unit tests must:

1. Take a known wall point `P`.
2. Project with `K`, `R`, `t` and match OpenCV `projectPoints`.
3. Transform `P` with `T_opencvCamMeters_wall` and obtain
   `s * (R_p X_colmap + t_p)` for the corresponding COLMAP point.
4. Invert and recover `P`.

A failed direction test is a Gate 6 blocker. Do not compensate in
rendering.

---

## 5. Camera-basis change: OpenCV ↔ ARKit

OpenCV camera: +Y down, +Z forward.
ARKit camera: +Y up, −Z forward.

The unique proper rotation (det = +1) that maps OpenCV camera
coordinates to ARKit camera coordinates is:

```text
S = diag(1, -1, -1)

p_arkitCam = S * p_opencvCam
```

As a 4×4:

```text
T_arkitCam_opencvCam = | 1  0  0  0 |
                       | 0 -1  0  0 |
                       | 0  0 -1  0 |
                       | 0  0  0  1 |
```

This lives in **one** function, e.g.
`CoordinateTransforms.openCVCameraToARKitCamera`.

No other file may write `y = -y` / `z = -z` for this purpose.

---

## 6. Production alignment after visual lock

**Prerequisite:** `S_wall_colmap.status = defined`. Otherwise
`productionAlignment` must throw / refuse. Gate 6–7 candidate poses in
COLMAP units are not an input to this function.

Frame chain:

```text
X_colmap
  → S_wall_colmap
  → X_wall_meters
  → T_opencvCamMeters_wall
  → T_arkitCam_opencvCam
  → T_ARWorld_arkitCam
  → X_ARWorld_meters
```

Inputs at lock time:

| Symbol | Meaning | Source |
|--------|---------|--------|
| `T_opencvCam_colmap` | PnP world-to-OpenCV-camera (recon units) | confirmed visual pose |
| `S_wall_colmap` | Sim(3) reconstruction → metric Wall | offline, status `defined` |
| `T_arkitCam_opencvCam` | §5 | Coordinates module |
| `T_ARWorld_arkitCam` | ARKit camera-to-world | `ARCamera.transform` at the **same** frame |

```text
R_cam_wall = R_p R_sᵀ
t_cam_wall = s * t_p - R_p R_sᵀ t_s

T_opencvCamMeters_wall = | R_cam_wall  t_cam_wall |
                         | 0           1          |

T_ARWorld_Wall =
    T_ARWorld_arkitCam
  * T_arkitCam_opencvCam
  * T_opencvCamMeters_wall
```

Do not freeze `T_opencvCam_colmap * inverse(S_wall_colmap)` as the
camera SE(3). That product is the Gate 4A metric defect (scale `1/s`).

ARKit’s `ARCamera.transform` is camera-to-world, in meters:

```text
p_ARWorld = T_ARWorld_arkitCam * p_arkitCam
```

This product is created only by `CoordinateTransforms.productionAlignment(...)`.
Rendering assigns `entity.transform = Transform(matrix: T_ARWorld_Wall)`
(or equivalent). No extra rotations. No identity stand-in for
`S_wall_colmap`.

After lock, ARKit tracking updates `T_ARWorld_arkitCam`. The wall entity
stays fixed in ARWorld; the camera moves. Visual Localization may later
recompute `T_ARWorld_Wall` (relocalization). That is a new production
alignment, not a nudge.

---

## 7. Query image and `K`

Let `K` be:

```text
K = | fx   0  cx |
    |  0  fy  cy |
    |  0   0   1 |
```

`ARCamera.intrinsics` matches `ARFrame.capturedImage` pixel space
(typically landscape).

If SIFT runs on a rotated or scaled copy of that buffer:

```text
[u']   = A [u]
[v']       [v]
[1 ]       [1]

K' = A * K
```

Keypoints used in PnP must be in the **same** pixel space as `K'`.

Distortion:

- Reference COLMAP camera for this wall is `SIMPLE_RADIAL` with
  `k ≈ -0.1104` on 5280×3956 DJI images. That coefficient applies to
  **those images**, not to the iPhone.
- iPhone `distCoeffs = (0,0,0,0,0)` unless a measured model is added.

Projection (OpenCV camera, no distortion):

```text
[x y z] = R * X_world + t
u = fx * x / z + cx
v = fy * y / z + cy
```

`X_world` is COLMAP XYZ for Gate 2–6, or metric Wall XYZ after
`S_wall_colmap` is defined. Require `z > ε`.

---

## 8. Forbidden patterns

These are defects, not style nits:

```text
entity.position += someOffset
rotation.y += 90°
swap(y, z)                 // outside Coordinates
x = -z                     // outside Coordinates
scale = 0.98               // “it looked better”
GPS ENU baked into T_ARWorld_Wall
using T_wall_enu = I
using S_wall_colmap = I because “the bbox looks like meters”
labeling raw COLMAP XYZ as meters
storing routes in ARWorld
storing routes in COLMAP units and rendering them as meters
```

No production `Translate` / `Rotate` / `Scale` UI.
No per-crag hardcoded correction.
No “visual fix” transform source.

If alignment is wrong, inspect: correspondences, PnP, `K`, transform
direction, frame IDs, route frame, Wall Frame.

---

## 9. Central module

All of the following live in `ios/RockVision/Domain/Coordinates/`:

- frame identifiers (enum / string IDs matching this document)
- `T_arkitCam_opencvCam`
- rvec/tvec → `T_opencvCam_colmap`
- `S_wall_colmap` application (refuses if status ≠ `defined`)
- `productionAlignment` (refuses if `S_wall_colmap` unknown)
- future `S_wall_enu` application
- test helpers for projection

Python exporter may duplicate the **same** named matrices in
`offline/exporter/transforms.py` for fixture generation. Values must
match unit tests.

---

## 10. Required unit tests (Gate 0+ as types appear)

Implement tests when the types exist; do not skip them later.

| Test | Assertion |
|------|-----------|
| `T_A_B` inverse | `T_B_A * T_A_B ≈ I` |
| OpenCV↔ARKit | `det(S) = +1`, `S * S = I` |
| OpenCV camera +Z | a point on +Z projects to `(cx, cy)` |
| PnP round-trip | synthetic `R,t` recovered within tolerance |
| Direction | `p_cam = T_opencvCam_colmap * p_colmap` matches `R p + t`; metric SE(3) is `T_opencvCamMeters_wall`, not `T * inverse(S)` |
| Production chain | known `P_wall` maps to expected `P_ARWorld` for a constructed camera **and** defined `S_wall_colmap` |
| Unknown `S_wall_colmap` | `productionAlignment` refuses; no identity fallback |
| Defined Sim(3) | `X_wall = S_wall_colmap * X_colmap` recovers the fixture |
| Unknown `S_wall_enu` | loader/renderer refuses ENU routes |
| Manual source | validator rejects `kind = manual` |

---

## 11. RealityKit / SceneKit

RealityKit world for this app **is** `arkit_world_gravity_heading_eus`
when the session uses gravity-and-heading. Entity transforms are
local-to-parent. The wall root is parented to world via
`T_ARWorld_Wall` only.

If a SceneKit path is ever added, it must use the same `T_A_B` types.
Do not add a second undocumented SceneKit conversion.

Session alignment is an implementation choice at Gate 8. If
`worldAlignment` is not gravity-and-heading, **update this document
first** and rename the ARWorld frame id. Do not leave a stale name.

---

## 12. COLMAP vs ENU (known gap)

Two independent gaps:

1. **Scale / Sim(3):** raw COLMAP is not proven metric (`S_wall_colmap` unknown).
2. **ENU registration:** V1 routes / Terra mesh are `local_enu_east_up_north_meters`.
   That frame is not COLMAP and is not Wall Frame until `S_wall_enu` is defined.

V1 marked `pendingGeometryRegistration`. V2 keeps both facts visible.

Gates 2–7 operate in COLMAP reconstruction units. Gate 8 test landmarks
must be **metric Wall** points. They cannot be raw COLMAP XYZ, and they
cannot be ENU route vertices, until the corresponding Sim(3) is solved.

Do not use bounding-box size as evidence that either gap is closed.
