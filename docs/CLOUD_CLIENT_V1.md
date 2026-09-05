# Cloud Asset Client v1 (iOS)

iPhone client for the frozen Cloud Asset API v1. This is a cache/install
layer only. Visual matching, PnP, AR, and route rendering stay on device
and must consume **local validated** assets, never live Cloud requests in
the camera loop.

This does **not** authorize production wall publishing, `routes.json`,
Jinshidong production, Stage 5 PASS, or `https://api.cragpal.com` as live.

## Base URL

Central type: `CloudAPIConfiguration`.

- Development (DEBUG default): temporary HTTP endpoint
  `http://124.223.178.91` — not the long-term contract.
- Production kind: `https://api.cragpal.com` — target only; ICP / DNS /
  HTTPS are not complete. Production is never pinned to a bare HTTP IP.

ATS allows insecure HTTP **only** for that development IP
(`NSExceptionDomains`, not `NSAllowsArbitraryLoads`).

## Routes

PRODUCTION discovery (Release / App Store):

- `GET /v1/walls`
- `GET /v1/walls/{wallId}/manifest`

DEBUG/TEST discovery (DEBUG builds):

- `GET /v1/debug/walls`
- `GET /v1/debug/walls/{wallId}/manifest`

Exact immutable release (unchanged, not catalog discoverability):

- `GET /v1/walls/{wallId}/releases/{releaseId}/manifest`
- `GET /v1/walls/{wallId}/releases/{releaseId}/assets/{assetId}`

`/v1/walls/{wallId}/assets/{assetId}` is not used.

Endpoint selection is compile-time `#if DEBUG`, not a user toggle and
not inferred from `wallId` suffix or display name.

Release clients also drop any catalog entry that is not explicitly
`environment == production`, even if a misconfigured backend returns it.
DEBUG may accept `production`, `development_test`, and unspecified
legacy compatibility fixtures. Unknown explicit environment fails
closed at decode.

## Discovery-driven install

Release path:

1. `GET /v1/walls`
2. choose a fetched catalog entry (`wallId` from that entry)
3. `GET /v1/walls/{wallId}/manifest` (production convenience)
4. freeze the **returned** `manifest.releaseId`
5. download exact immutable assets for that frozen identity
6. verify bytes + SHA-256
7. atomically point wall-scoped CURRENT

DEBUG path uses `/v1/debug/walls` and
`/v1/debug/walls/{wallId}/manifest` for the same sequence.

Catalog `latestReleaseId` is discovery metadata only. The installer does
not send it. The installation transaction trusts the validated manifest
identity returned by the convenience endpoint.

Explicit `GET /v1/walls/{wallId}/releases/{releaseId}/manifest` /
`installRelease(wallId:releaseId:)` remains debug/test-only (Jiulongfeng
Dev). That is **not** catalog discovery and does **not** switch camera
localization off the Bundle development fixture. Exact release
accessibility is not production qualification.

The backend owns projection of promotion records and the transitional
legacy merge. The App does not enumerate `published/promotions/`.

Asset downloads always use the frozen `manifest.releaseId`.

## Local cache

```text
Application Support/CloudAssets/walls/<wallId>/
  current.json
  releases/<releaseId>/manifest.json
  releases/<releaseId>/assets/<assetId>
  staging/<releaseId>/...
```

CURRENT is a **per-wallId** pointer
(`CloudAssets/walls/<wallId>/current.json`), updated only after every
required asset passes bytes + SHA-256. Installing one wall does not
replace another wall's CURRENT. There is no global CURRENT pointer.
A failed/interrupted update leaves the previous CURRENT for that wall
in place.

Published `releaseId` directories are immutable. If `releases/<releaseId>`
already exists and matches the server manifest, install is a reuse/no-op.
If it exists but the new manifest conflicts, or the local tree is corrupt,
install fails closed and does not overwrite that directory.

`localAssetURL` returns a URL only when CURRENT is valid, the asset is in
the manifest, the file exists, and bytes + SHA-256 verify. Failed optional
assets are not exposed.

## Debug HUD (D5)

DEBUG field-test UI follows **active test phase owns the debug HUD**
([`DEBUG_HUD.md`](DEBUG_HUD.md)). The D5 primary surface is Cloud
discovery/install only. Historical Cloud debug controls (example
Download/Update, explicit Jiulongfeng install, Bundle/Cloud reference
source) remain implemented and must not be deleted; they are hidden
while `DebugHUDMode.active` is `cloudD5`.

## Localization input bridge

Cloud distribution → local validated CURRENT release →
`ReferenceAssetSource` → existing `ReferenceDatabase.load`.

The camera / matching loop consumes **local file URLs only**. It does not
call `fetchCatalog`, `fetchManifest`, `downloadAsset`, or `URLSession`.
Catalog discovery / `refreshAndInstall(wallId:)` does not select a
localization reference source. Stage 3 Cloud CURRENT remains the
explicit Jiulongfeng Dev debug action.

Selection is explicit:

- development fixture mode → Bundle `DevelopmentFixture`
- cloud wall mode → validated local CURRENT via `localValidatedRelease` /
  `localAssetURL`

Cloud mode does **not** fall back to Bundle.

Cloud Asset Contract v1 freezes Stage 3 semantic types:

- `reference_descriptors_rvs1`
- `reference_landmarks_json`

A Cloud Stage 3 package must contain exactly one **required** asset of
each type. The client resolves by semantic `type`, then uses the
concrete opaque `assetId` with `localAssetURL`. `assetId` is not a
filename.

`wall_example_01` / `r000001` / 38-byte `reference-map`
(`type: reference_map`) is not a ReferenceDatabase.

A DEVELOPMENT_TEST_ONLY COS release (`wall_jiulongfeng_01_dev` /
`r000001`) is installed through the explicit release path (not catalog
discovery) and may be selected as the localization source by an
explicit Debug action. Camera default remains the Bundle
`DevelopmentFixture`. Cloud failure does not fall back to Bundle.
The camera / matching loop stays network-free after CURRENT is local.

**CLOUD_HOSTED_STAGE3_LOCALIZATION_E2E = PASS** (2026-09-04,
DEVELOPMENT_TEST_ONLY). Real-device Debug Cloud CURRENT
`wall_jiulongfeng_01_dev` / `r000001`: Unique 3D 618, PnP inliers 451,
PnP status `candidate`, Confirm 3/3, Localization `localized`,
`T_ARWorld_Wall` valid, route rendered YES. This proves Cloud-hosted
Stage 3 reference assets can drive the existing real-device
localization pipeline. Localization math is unchanged. This does
**not** mean Jiulongfeng is production published, Jinshidong production
Reference Map is valid, a production wall package exists, Stage 5
PASS, Gate 5D-B PASS, or social/cloud production launch.

Offline localization uses previously downloaded local assets, never live
Cloud requests.

## ATS (temporary)

DEBUG may use the development HTTP IP. Release `CloudAPIConfiguration.default`
is `https://api.cragpal.com`.

The Info.plist ATS exception for `124.223.178.91` is a **temporary
development** allowance (`TEMPORARY_ACCEPTABLE`). It is **not** permanent
production configuration.

Before production / App Store release:

- remove the IP ATS exception from Release
- production endpoint remains `https://api.cragpal.com`
