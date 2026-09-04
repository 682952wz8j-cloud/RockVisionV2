# Production Localization Package v1

Local, unpublished contract for a future **Production Localization Package**.

This document defines a validator-facing data model. It does **not**
authorize publication, COS upload, catalog promotion, iOS runtime
consumption of a new Sim(3) Cloud type, or Route AR.

## What this is

A Production Localization Package is a **LOCALIZATION_READY** candidate:
the three inputs a new wall needs to reach the existing confirmed
`localized` state, bound to a proven Stage 2 Reference Map.

Required localization inputs:

1. `reference_descriptors_rvs1`
2. `reference_landmarks_json`
3. validated `S_wall_colmap` (metric Sim(3))

Descriptors + landmarks are sufficient Cloud matching/PnP **input**.
They are **not** sufficient for a new arbitrary wall to reach confirmed
`localized`. The runtime also requires the validated metric transform.

## What this is not

Keep these identities separate:

| Concept | This phase |
|---------|------------|
| Stage 2 Build (`./rockvision build` / `wall_build`) | source evidence, not a package |
| Stage 3 Generation (`./rockvision reference-match`) | descriptor/landmark freeze, not a package |
| **Localization Package** | this contract (local candidate only) |
| Publish Approval | not implemented |
| Published Release | not written; never `published/` |
| Catalog Promotion | unchanged |
| Route AR Package | explicitly excluded |

**BUILD ≠ PUBLISHED.** Copying files into `offline/packages/` is
`CONSTRUCTED`, not `PACKAGE_READY`, and never a Cloud release.

Do not call this a Full Wall Package, Route Package, or Route AR
Package. Routes are excluded.

| Capability | v1 |
|------------|----|
| `LOCALIZATION_READY` | possible after local validation |
| `ROUTE_AR_READY` | always `false` |

No `routes.json`. No `route_test_01`. No Gate 5D-B assets. No Stage 5
package output. `LOCALIZATION_READY` does not imply `ROUTE_AR_READY`.

## Local directory contract

```text
offline/packages/<wallId>/<releaseId>/
    package.json
    cloud-manifest.json
    assets/
        <opaque assetId>     # descriptors
        <opaque assetId>     # landmarks
        <opaque assetId>     # S_wall_colmap JSON
    evidence/
        stage2_input_selection.json
        positioning_quality.json
        height_vertical_datum.json
        colmap_source_identity.json
        freeze.json
```

`releaseId` syntax is `rNNNNNN`. This phase does **not** allocate the
next release and does **not** query COS.

Do not write under COS layout. Do not write `published/`.

## package.json schema

Schema name: `cragpal.localization-package.v1`

Minimum bindings:

- identity: `schema`, `wallId`, `releaseId`, `environment`
  (`production` \| `development_test`)
- capabilities: `localizationReady`, `routeArReady`
- source build: exact `wall_build` `runId`, Stage 2 selection identity,
  selected source JPEG SHA-256 map, positioning-quality result,
  height-datum result, COLMAP source identity / `modelFingerprint`
- metric registration: `S_wall_colmap` source, `status`, SHA-256, bytes
- Stage 3: descriptor type/SHA-256/bytes, landmark type/SHA-256/bytes,
  freeze identity when the freeze actually records it
- routes: `{ "present": false, "authorized": false }`
- `packageState`: `CONSTRUCTED` \| `NOT_PACKAGE_READY` \| `PACKAGE_READY`

Construction may write `CONSTRUCTED`. Only the validator may conclude
`PACKAGE_READY`. Declaring `PACKAGE_READY` or `localizationReady: true`
without passing validation is `DECLARED_STATE_MISMATCH`.

Do not fabricate provenance current artifacts cannot prove. Missing
bindings fail closed or are recorded as `NOT_PROVEN` reason codes.
Directory names, timestamps, and filenames are not proof.

## Package state

| State | Meaning |
|-------|---------|
| `CONSTRUCTED` | files were written; not validated |
| `NOT_PACKAGE_READY` | validation ran; mandatory provenance failed |
| `PACKAGE_READY` | all mandatory **local** provenance checks passed |

`PACKAGE_READY` is not publish authorization.

## Production environment

For `environment = production` the contract rejects Stage 3 landmarks
with:

- `developmentFixtureOnly = true`
- `notAWallPackage = true`

The Stage 3 generator is unchanged in this phase. Current Jiulongfeng
frozen fixture stamps both flags `true` and therefore **must not**
qualify as a production package.

Jinshidong remains blocked by positioning-quality policy
(`POSITIONING_QUALITY_NOT_PROVEN`). That evidence cannot become
`PACKAGE_READY`. This phase does not package either wall.

`development_test` may represent development-test package semantics.
It must never weaken production validation.

## Metric transform

Do not treat “a `S_wall_colmap.json` file exists” as validation.

Production package validation requires:

- `status = VALIDATED`
- wall identity **inside the JSON** compatible with the package `wallId`
- COLMAP `modelFingerprint` **inside the JSON** compatible with the
  selected Stage 2 identity evidence
- finite transform values and `scale > 0` (existing Sim(3) contract;
  no new math, no threshold changes)
- SHA-256 + bytes recorded and matching the asset bytes

Parsing reuses `offline.metric_registration.serialize.load_sim3`.

New `wall_build` metric-registration writes stamp `wallId`,
`wallBuildRunId`, and `colmapModelFingerprint` (same value as Stage 2
`modelFingerprint`). Historical on-disk `S_wall_colmap.json` may omit
those fields: it remains parseable and fails production package
validation closed (`WALL_ID_MISMATCH` /
`SIM3_WALL_BUILD_RUN_MISMATCH` / `COLMAP_SOURCE_IDENTITY_NOT_PROVEN` /
`SIM3_MODEL_FINGERPRINT_MISMATCH`). Do not infer identity from paths.

## Stage 3 ↔ Reference Map cross-binding

Production Stage 3 generation binds an **explicit** validated
`wall_build/<runId>`:

```text
./rockvision reference-match <wall_id> --run-id <runId>
```

No latest-run selection. No fallback to
`offline/work/<wallId>/colmap` or `metric_registration` in production
mode. Without `--run-id`, the existing development/legacy path remains.

A production-bound freeze records `wallId`, `wallBuildRunId`, and
`colmapModelFingerprint` from the selected run’s
`colmap_source_identity.json` after re-hashing the live model
(`modelFingerprint` is reused, not replaced). New `S_wall_colmap.json`
writes from `wall_build` stamp the same identity. Historical Sim3/freeze
files remain readable and stay `NOT production PACKAGE_READY` if those
fields are absent.

The package validator requires equality across package, Stage 2
identity, Sim3, freeze, and landmarks. Paths are not proof.

This does **not** mark any real wall `PACKAGE_READY`. Jiulongfeng
DevelopmentFixture remains development-only. Jinshidong remains
`POSITIONING_QUALITY_NOT_PROVEN`.

## Local cloud-manifest candidate

File: `cloud-manifest.json`

Schema: `cragpal.wall-manifest.v1` (same wire document as Cloud Asset
Contract v1). Generated and validated locally. **Not uploaded.**

Required semantic types (each exactly once, `required: true`):

| `type` | Role |
|--------|------|
| `reference_descriptors_rvs1` | Stage 3 descriptors |
| `reference_landmarks_json` | Stage 3 landmarks |
| `s_wall_colmap_json` | validated `S_wall_colmap` JSON |

`type` is already an extensible string on the manifest. `s_wall_colmap_json`
is a **proposed** precise semantic type for this package contract.

Current iOS `CloudStage3AssetSemantics` consumes only descriptors +
landmarks. It does **not** consume `s_wall_colmap_json`. Runtime support
is a later phase. This local contract is ahead of current iOS
consumption. Do not claim the Cloud E2E on Jiulongfeng Dev proves Cloud
Sim(3) delivery.

## Local production package E2E (synthetic)

A synthetic production-positive fixture (`wall_pkg_e2e_01`) proves the
local chain:

validated `wall_build/<runId>`
→ production `reference-match --run-id`
→ construct under `offline/packages/`
→ validate
→ `PACKAGE_READY` / `LOCALIZATION_READY`

`ROUTE_AR_READY` remains false. No routes. No COS. The production-bound
generator still reports Gate 3C `NEEDS REVIEW` (Swift/handoff review).
That status is outside package validation.

**LOCAL PACKAGE E2E PASS ≠ CLOUD PUBLICATION PASS ≠ REAL WALL PRODUCTION PASS.**

This does not mark Jinshidong or Jiulongfeng production-ready. Publishing
is not implemented. iOS still does not consume Cloud Sim(3).

## Stage 3 generation vs package readiness

Keep these distinct:

| Concept | Meaning |
|---------|---------|
| Stage 3 generation complete | `reference-match` produced descriptors/landmarks |
| Stage 3 assets frozen | `freeze.json` records SHA-256/bytes of those assets |
| Stage 3 provenance proven | freeze/Sim3/Stage 2 wall + run + `modelFingerprint` match |
| Stage 3 qualification/review | Gate 3C `NEEDS REVIEW` compatibility/Swift handoff |
| `PACKAGE_READY` | mandatory **local provenance** checks passed |
| Publish approval | not implemented |
| Published | not written; never COS / `published/` |

Gate 3C `build_reference_matching` always ends successful freeze with
`stage=compatibility_human_review`, `gateResult=NEEDS REVIEW`,
`humanReviewRequired=true`, `stopBeforeSwift=true`. That is a historical
development handoff before Swift. The generator never auto-assigns
`PASS`. The CLI exits 0 on `NEEDS REVIEW` and 1 only on `STOP`/errors.

That handoff is **outside** Production Localization Package validation.
`PACKAGE_READY` does not require Gate 3C `PASS`. Freeze existence is
not Stage 3 PASS. `PACKAGE_READY` ≠ publish approved ≠ published.

## Remaining blockers before a real PACKAGE_READY wall

- No real wall has been run through production `--run-id` Stage 3 yet.
  A synthetic local E2E can reach `PACKAGE_READY`; that is not a real
  production wall.
- Jiulongfeng DevelopmentFixture remains `developmentFixtureOnly` /
  `notAWallPackage` and is byte-frozen.
- Jinshidong positioning quality is not proven.
- Historical Sim3/freeze without provenance stay readable and
  not production `PACKAGE_READY`.
- No publisher, no COS write, no catalog, no release allocation.
- iOS does not load Cloud `S_wall_colmap`.
