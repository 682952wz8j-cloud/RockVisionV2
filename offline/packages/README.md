# offline/packages

Local Production Localization Package candidates only.

Layout:

```text
offline/packages/<wallId>/<releaseId>/
    package.json
    cloud-manifest.json
    assets/
    evidence/
```

This directory is **not** COS layout and is **not** `published/`.
A directory here is not a Cloud release. See
[`docs/PRODUCTION_LOCALIZATION_PACKAGE_V1.md`](../../docs/PRODUCTION_LOCALIZATION_PACKAGE_V1.md).

Phase A does not write real wall packages. Synthetic fixtures live in
tests only.
