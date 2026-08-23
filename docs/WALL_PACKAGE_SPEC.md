# Wall Package Specification

Status: Gate 1 schema (document only). No package files have been generated.

A **Wall Package** is the only runtime payload consumed by Visual
Localization, coordinate transforms, and route rendering.

Providers (`BundleWallDataProvider`, later cache/remote) resolve a `wallId`
to a `WallPackage`. Algorithms do not care which provider succeeded.

---

## 1. Design rules

1. **Versioned.** The app rejects unknown major versions.
2. **Separated payloads.** Localization, routes, and visual model are
   independent artifacts. A future download may fetch localization +
   routes without the mesh.
3. **Visual model is optional.** Localization must work with zero mesh
   bytes.
4. **Two geometry frames.** Localization records store raw COLMAP XYZ
   in reconstruction units, plus `point3DId`. The production Wall Frame
   is metric. `S_wall_colmap ∈ Sim(3)` maps COLMAP → Wall meters.
   Routes and production AR consume **only** metric Wall coordinates
   after `S_wall_colmap.status = defined`.
5. **No GPS in localization data.** Catalog WGS84 may appear on the
   manifest for candidate selection only.
6. **No screen / camera / ARWorld coordinates** stored for routes or
   landmarks.
7. **No SuperPoint / `.rvloc` compatibility.** This is a new format.

---

## 2. On-disk layout

Package root is a directory named `{wallId}/`.

```text
{wallId}/
  manifest.json                 required
  localization/
    landmarks.json              required (Gate 2)
    descriptors.bin             required (Gate 2)
    association_report.json     offline / debug; optional on device
  routes/
    routes.json                 required for Gates 9–10; may be omitted earlier
  coordinates/
    frames.json                 required
  visual/                       optional entire directory
    model.usdz                  optional
    model.rvmesh                optional debug mesh
  checksums.json                required
```

Bundle copy (later):

```text
ios/RockVision/Resources/Walls/{wallId}/...
```

Data flow (do not skip stages):

```text
incoming/{wallId}/     immutable raw source
        ↓ Gate 1A inventory.json
offline/work/{wallId}/ generated intermediates
walls/{wallId}/        this package — only input to WallDataProvider
```

`incoming/` is never a Wall Package. `offline/work/` is never loaded by
the iPhone. Cloud delivery later copies `walls/`, not `incoming/`.

---

## 3. Versioning

`manifest.packageVersion` is `MAJOR.MINOR`.

| Component | Compatibility |
|-----------|----------------|
| MAJOR | Breaking schema or coordinate-frame meaning |
| MINOR | Additive fields; older readers ignore unknowns |

Current: **`1.0`**.

`localization.schema` and `routes.schema` have their own integers so a
payload can evolve without bumping the whole package when unnecessary.
For V2 both start at `1`.

---

## 4. `manifest.json`

```json
{
  "packageVersion": "1.0",
  "wallId": "wall_jiulongfeng_01",
  "wallName": "九龙峰森林站大楼",
  "cragId": "crag_jiulongfeng",
  "createdAt": "2026-08-23T00:00:00Z",
  "generator": "rockvision-v2-exporter",
  "generatorVersion": "0.1.0",

  "catalogLocation": {
    "purpose": "wall_candidate_selection_only",
    "latitudeDeg": 30.12995549580355,
    "longitudeDeg": 118.01498918025646,
    "altitudeMeters": 314.93690953788564
  },

  "payloads": {
    "localization": {
      "present": true,
      "path": "localization/landmarks.json",
      "descriptorsPath": "localization/descriptors.bin",
      "requiredForVisualLocalization": true
    },
    "routes": {
      "present": false,
      "path": "routes/routes.json",
      "requiredForVisualLocalization": false
    },
    "visualModel": {
      "present": false,
      "path": null,
      "requiredForVisualLocalization": false
    },
    "coordinates": {
      "present": true,
      "path": "coordinates/frames.json"
    }
  }
}
```

### Field rules

| Field | Rule |
|-------|------|
| `wallId` | Stable string. Matches folder name |
| `catalogLocation` | Optional. **Never** read by `VisualLocalizer` |
| `payloads.*.requiredForVisualLocalization` | If `true` and missing → load fails before search |
| `visualModel` | Absence is success for VL |

The iOS loader must refuse to start `searching` if localization payload
or coordinates payload is missing or checksum-invalid.

---

## 5. `coordinates/frames.json`

See [COORDINATE_CONVENTIONS.md](COORDINATE_CONVENTIONS.md) for mathematics.
This file only **names** the frames stored in the package and records
known transforms.

```json
{
  "reconstructionUnits": "arbitrary",
  "wallUnits": "meters",
  "wallFrameId": "wall_metric_rhs_opencv_meters",
  "colmapFrameId": "colmap_reconstruction_rhs_opencv_units",
  "frames": [
    {
      "id": "colmap_reconstruction_rhs_opencv_units",
      "role": "colmap_reconstruction",
      "units": "arbitrary_reconstruction_units"
    },
    {
      "id": "wall_metric_rhs_opencv_meters",
      "role": "wall",
      "units": "meters"
    },
    {
      "id": "local_enu_east_up_north_meters",
      "role": "legacy_v1_routes_and_terra",
      "units": "meters",
      "packageStatus": "not_authoritative"
    }
  ],
  "transforms": [
    {
      "name": "S_wall_colmap",
      "from": "colmap_reconstruction_rhs_opencv_units",
      "to": "wall_metric_rhs_opencv_meters",
      "convention": "X_wall_meters = S_wall_colmap * X_colmap",
      "kind": "sim3",
      "scale": null,
      "rotationRowMajor3x3": null,
      "translation": null,
      "matrix4x4RowMajor": null,
      "status": "unknown",
      "note": "Jiulongfeng COLMAP is incremental SfM only. Not proven metric. Gate 8 blocked."
    },
    {
      "name": "S_wall_enu",
      "from": "local_enu_east_up_north_meters",
      "to": "wall_metric_rhs_opencv_meters",
      "kind": "sim3",
      "status": "unknown",
      "matrix4x4RowMajor": null,
      "note": "V1 routes must not be rendered until this is computed offline"
    }
  ]
}
```

### Loader enforcement

- Localization landmark `xyz` is **COLMAP reconstruction units**.
  Field `xyzFrameId` must equal `colmapFrameId`. Do not label it meters.
- `X_wall_meters = S_wall_colmap * X_colmap` only when
  `S_wall_colmap.status == "defined"`.
- If `S_wall_colmap.status != "defined"`, the app may run Gates 2–6
  PnP in COLMAP units. It **must refuse** `productionAlignment` and
  route/landmark placement in ARWorld.
- Route files must declare `coordinateSystem == wallFrameId` (metric).
- If a route file declares `local_enu_east_up_north_meters` and
  `S_wall_enu.status != "defined"`, the renderer **must refuse** those
  routes. Do not apply identity. Do not apply `S_wall_colmap = I`.

---

## 6. Localization payload

### 6.1 `localization/landmarks.json`

Human-readable index + per-landmark metadata. Descriptors are **not**
embedded (they are large); they live in `descriptors.bin` in the same
order as `landmarks[]`.

```json
{
  "schema": 1,
  "wallId": "wall_jiulongfeng_01",
  "xyzFrameId": "colmap_reconstruction_rhs_opencv_units",
  "xyzUnits": "arbitrary_reconstruction_units",
  "sift": {
    "implementation": "opencv",
    "opencvVersion": "TBD_at_gate_3",
    "nfeatures": 0,
    "nOctaveLayers": 3,
    "contrastThreshold": 0.04,
    "edgeThreshold": 10,
    "sigma": 1.6,
    "descriptorDim": 128,
    "descriptorDtype": "float32",
    "descriptorRowMajor": true
  },
  "matchingHints": {
    "knnK": 8,
    "ratioThreshold": 0.8,
    "distanceType": "l2",
    "matchUnit": "unique_point3d",
    "minDistinctPoint3DForRatio": 2
  },
  "referenceImages": [
    {
      "id": 1,
      "name": "DJI_20260812152953_0001_V.JPG",
      "width": 5280,
      "height": 3956,
      "colmapImageId": 1,
      "registered": true
    }
  ],
  "landmarks": [
    {
      "index": 0,
      "referenceImageId": 1,
      "keypoint": {
        "x": 1960.01,
        "y": 812.44,
        "size": 5.2,
        "angleDeg": 37.1,
        "octave": 0,
        "response": 0.04
      },
      "point3DId": 10422,
      "xyz": [-1.203, 2.441, 3.018]
    }
  ]
}
```

`xyz` is COLMAP reconstruction XYZ. Several `landmarks[]` rows **may
share** one `point3DId` (multi-view observations). That is expected.
Matching must collapse to unique `point3DId` before the ratio test and
before PnP. See architecture §9.6.

| Field | Meaning |
|-------|---------|
| `index` | Dense 0…N−1. Equals row in `descriptors.bin` |
| `referenceImageId` | Package-local image id |
| `keypoint.x/y` | Pixels in the **reference image** used for OpenCV extract (native JPG unless a documented shared scale is applied) |
| `point3DId` | Original COLMAP `POINT3D_ID`. Never remapped away; a dense index may be added later but COLMAP id is preserved |
| `xyz` | COLMAP reconstruction XYZ (not meters unless `S_wall_colmap` is defined and applied) |

**Rejected features do not appear.** No `-1` point ids in the shipped table.

### 6.2 `localization/descriptors.bin`

Little-endian binary.

```text
magic        4 bytes   "RVS1"
version      u32       1
dtype        u32       1 = float32
dim          u32       128
count        u32       N  (must equal landmarks.length)
payload      N * 128 * 4 bytes, row-major, C order
```

`dtype` exists so a later package can store `uint8` without pretending
the values are still float32. V2 Gate 2 writes float32 (OpenCV default
SIFT output).

The iPhone matcher must fail fast if `count`, `dim`, or `dtype` disagree
with `landmarks.json`.

### 6.3 `association_report.json`

Required from the exporter. Optional inside the app bundle.

```json
{
  "wallId": "wall_jiulongfeng_01",
  "colmapModel": ".../sfm",
  "registeredImages": 62,
  "colmapPoints3D": 53472,
  "colmapObservationsWith3D": 211827,
  "opencvFeaturesTotal": 0,
  "candidateAssociations": 0,
  "acceptedLandmarks": 0,
  "rejected": {
    "noSpatialNeighbor": 0,
    "ambiguous": 0,
    "notMutual": 0,
    "noPoint3D": 0
  },
  "usablePercentOfOpenCVFeatures": null,
  "usablePercentOfColmapObservations": null,
  "S_wall_colmap_status": "unknown",
  "xyzAreMeters": false,
  "association": {
    "maxPixelDistance": 2.0,
    "uniquenessRatio": 0.7,
    "useScale": true,
    "maxScaleRatio": 1.5,
    "useOrientation": true,
    "maxOrientationDeg": 30.0,
    "usedDescriptorDistanceToColmap": false
  },
  "perImage": []
}
```

`usedDescriptorDistanceToColmap` must be `false`.

Exact numeric thresholds above are **exporter development defaults**, not
calibrated science. Gate 2 may change them if the report justifies it.

---

## 7. Route payload

### 7.1 `routes/routes.json`

```json
{
  "schema": 1,
  "wallId": "wall_jiulongfeng_01",
  "coordinateSystem": "wall_metric_rhs_opencv_meters",
  "routes": [
    {
      "id": "route_1",
      "name": "route 1",
      "grade": "5.10a",
      "boltCount": 5,
      "polyline": [
        { "x": 0.0, "y": 0.0, "z": 0.0, "order": 0 }
      ]
    }
  ]
}
```

Rules:

- `polyline` has at least two points.
- Units: meters.
- `coordinateSystem` **must** equal `frames.json` `wallFrameId`
  (`wall_metric_rhs_opencv_meters`).
- Do not store lat/lon, pixels, or ARWorld points.
- Product metadata (`grade`, `boltCount`, …) is allowed and ignored by
  localization.

### 7.2 V1 route files

V1 `route_*.json` use `coordinateSystem: "local_enu_east_up_north_meters"`.
They are **not** valid V2 route payloads until rewritten through a
defined `S_wall_enu` (and a defined `S_wall_colmap` if the destination
is metric Wall) or re-digitized in metric Wall Frame.

Gate 2 does not require routes. Gate 9 requires exactly one valid
metric-Wall polyline **and** `S_wall_colmap.status = defined`.

---

## 8. Visual model (optional)

Not used by Visual Localization.

If present, the model’s native coordinates must be stated in
`frames.json`. If they are not Wall Frame, a defined `T_wall_model` is
required. Identity is not assumed.

Debug axes / test landmarks for Gate 8 are **not** the visual model.
They are generated in code from known Wall XYZ.

---

## 9. `checksums.json`

```json
{
  "algorithm": "sha256",
  "files": {
    "manifest.json": "<hex>",
    "localization/landmarks.json": "<hex>",
    "localization/descriptors.bin": "<hex>",
    "coordinates/frames.json": "<hex>"
  }
}
```

`checksums.json` does not checksum itself. The loader hashes each listed
file.

---

## 10. In-memory model (iOS)

Conceptual Swift types (names may be adjusted at implementation):

```text
WallPackage
  manifest: WallManifest
  coordinates: CoordinateMetadata
  localization: LocalizationDatabase?
  routes: [RoutePolyline]
  visualModelURL: URL?

LocalizationDatabase
  sift: SIFTParameterSet
  images: [ReferenceImage]
  landmarks: [Landmark]          // xyz + keypoint + point3DId
  descriptors: DescriptorStore   // N × 128 float32

Landmark
  query is never stored
  only reference side
```

`VisualLocalizer` takes `LocalizationDatabase` + query frame.
`Renderer` takes `routes` + `T_ARWorld_Wall`.
Neither takes `CLLocation`.

---

## 11. Provider resolution

```text
protocol WallDataProvider {
  func loadPackage(wallId: String) throws -> WallPackage
}

enum WallPackageLoadError {
  case notFound
  case unsupportedVersion
  case missingRequiredPayload
  case checksumMismatch
  case coordinateSystemMismatch
  case descriptorCountMismatch
}
```

Current implementation target: `BundleWallDataProvider` reading
`Resources/Walls/{wallId}/`.

Future:

```text
CachedWallDataProvider   // Local Cache first
RemoteWallDataProvider   // not built
```

A composing provider may try cache → bundle → remote. Remote is out of
scope.

---

## 12. What this spec deliberately omits

- HTTP APIs
- SuperPoint / 256-D descriptors
- GPS-derived poses
- Manual T/R/S correction fields
- Per-phone alignment overrides
- Embedding the full Terra PLY
