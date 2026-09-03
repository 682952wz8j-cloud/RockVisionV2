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

The client only builds:

- `GET /v1/walls`
- `GET /v1/walls/{wallId}/manifest`
- `GET /v1/walls/{wallId}/releases/{releaseId}/assets/{assetId}`

`/v1/walls/{wallId}/assets/{assetId}` is not used.

Asset downloads always use the frozen `manifest.releaseId`.

## Local cache

```text
Application Support/CloudAssets/walls/<wallId>/
  current.json
  releases/<releaseId>/manifest.json
  releases/<releaseId>/assets/<assetId>
  staging/<releaseId>/...
```

CURRENT is a pointer updated only after every required asset passes
bytes + SHA-256. A failed/interrupted update leaves the previous CURRENT
in place.

Published `releaseId` directories are immutable. If `releases/<releaseId>`
already exists and matches the server manifest, install is a reuse/no-op.
If it exists but the new manifest conflicts, or the local tree is corrupt,
install fails closed and does not overwrite that directory.

`localAssetURL` returns a URL only when CURRENT is valid, the asset is in
the manifest, the file exists, and bytes + SHA-256 verify. Failed optional
assets are not exposed.

## ATS (temporary)

DEBUG may use the development HTTP IP. Release `CloudAPIConfiguration.default`
is `https://api.cragpal.com`.

The Info.plist ATS exception for `124.223.178.91` is a **temporary
development** allowance (`TEMPORARY_ACCEPTABLE`). It is **not** permanent
production configuration.

Before production / App Store release:

- remove the IP ATS exception from Release
- production endpoint remains `https://api.cragpal.com`
