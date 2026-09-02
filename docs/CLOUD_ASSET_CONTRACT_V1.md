# CragPal Cloud Asset Contract v1

Repository source of truth for the iPhone client. This document freezes
client rules for cloud-distributed wall assets. It does **not** authorize
production publishing, HTTPS, a public domain, ICP filing, iOS changes,
or Stage 5 / Gate status changes.

Schema names:

- Catalog: `cragpal.wall-catalog.v1`
- Manifest: `cragpal.wall-manifest.v1`

The RockVision repository, bundle identifiers, and internal Stage/Gate
names are unchanged.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Process liveness. No COS credentials required. |
| GET | `/v1/walls` | Published wall catalog only. |
| GET | `/v1/walls/{wall_id}/manifest` | Convenience: currently published immutable release. |
| GET | `/v1/walls/{wall_id}/releases/{release_id}/assets/{asset_id}` | Bytes for one asset in that exact immutable release. |

There is no public `/cos-test` route, no generic `/assets/{asset_path}`
proxy, and no `GET /v1/walls/{wall_id}/assets/{asset_id}`. The App must
never construct COS object keys, bucket names, COS hostnames, SecretId,
or SecretKey.

## Release binding

`GET /v1/walls/{wall_id}/manifest` may resolve `catalog.latestReleaseId`
and return that release's manifest.

That manifest contains `releaseId` (v1: `rXXXXXX`). The client must then
request every asset using **that exact** `releaseId`:

`GET /v1/walls/{wall_id}/releases/{release_id}/assets/{asset_id}`

The asset endpoint does **not** consult `latestReleaseId`. Lookup is
exactly `(wallId, releaseId, assetId)` → immutable object
`published/{wallId}/{releaseId}/assets/{assetId}`.

Published releases are immutable. Changing `latestReleaseId` cannot
change bytes returned for an older `releaseId`. A download that started
against an older READY/`releaseId` can complete after a newer release
becomes latest.

The asset endpoint does not require `release_id` to equal the wall's
current `latestReleaseId`. There is no release-listing API in v1.

## Identifiers

`wallId` is the permanent identity of a wall. A human-readable `name` may
change. `wallId` must remain stable.

`releaseId` is a wall-specific immutable published release identifier.
v1 format: `r000001`, `r000002`, …. Once published, a release must never
be modified in-place.

`assetId` and `type` are separate. The client must not infer asset meaning
from COS filenames or extensions.

The backend owns the mapping `(wallId, releaseId, assetId) → COS object
key`. Unknown wall IDs, release IDs, and asset IDs fail closed (404).
Identifiers that contain `..`, `/`, `\`, `:`, `@`, or other unsafe forms
are rejected (400). Invalid `releaseId` (not `r` + six digits) is 400.
The caller cannot inject an arbitrary COS key.

## BUILD ≠ PUBLISHED

A generated wall asset is not automatically eligible for cloud
publication. Only an explicitly published immutable release may appear
through the v1 catalog, manifest, and asset endpoints.

The API must not auto-discover files from `walls/`, `validation/`,
`incoming/`, or offline output. This contract does not create a
production route package, does not create `routes.json`, and does not
reinterpret Stage/Gate status.

## Frozen client rules

### A. Cloud distributes assets only

Cloud delivers published bytes. Visual matching, PnP, pose estimation,
AR alignment, and rendering remain local on iPhone.

### B. Manifest is the only download contract

The App downloads only assets listed in the manifest for one
`releaseId`. It must not guess extra objects from filenames, prefixes,
or a filesystem/COS listing.

### C. One release is one compatible set

All required assets within one release form one compatible set. Never
mix required assets from different `releaseId`s.

### D. Every asset record must contain

- `assetId`
- `type`
- `required`
- `bytes`
- `sha256`

### E. Download validity

An asset is valid only when **both** are true:

- actual byte count == `manifest.bytes`
- SHA256(file) == `manifest.sha256` (64 lowercase hex characters)

### F. Atomic activation

A new release cannot become CURRENT until all required assets are
downloaded and verified.

### G. Failed updates must not damage READY

A failed, corrupt, or incomplete update must not damage the previous
READY release.

### H. Offline behavior

If the network is unavailable, the App may continue using the most
recent complete locally READY release.

## Suggested client states

```text
NOT_INSTALLED
DOWNLOADING
VERIFYING
READY
FAILED
CORRUPT
```

Only `READY` may become `CURRENT`.

## Example catalog

```json
{
  "schema": "cragpal.wall-catalog.v1",
  "walls": [
    {
      "wallId": "wall_example_01",
      "name": "Example Wall",
      "latestReleaseId": "r000001"
    }
  ]
}
```

## Example manifest

```json
{
  "schema": "cragpal.wall-manifest.v1",
  "wallId": "wall_example_01",
  "releaseId": "r000001",
  "createdAt": "2026-09-02T15:30:00Z",
  "assets": [
    {
      "assetId": "reference-map",
      "type": "reference_map",
      "required": true,
      "sha256": "<64 lowercase hex characters>",
      "bytes": 123456
    }
  ]
}
```

Repository tests use a synthetic example wall only. That fixture is not
a production publication.

## Status

Repository implementation of this contract is recorded in the root
README under Cloud Backend Phase 1 / Cloud Asset Contract v1. Repository
IMPLEMENTED does **not** mean production asset publishing is authorized
and does **not** change Stage 5 Gate status.
