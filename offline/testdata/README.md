# Offline test fixtures

Gate 1A ingestion tests use isolated fixtures under
`offline/testdata/ingestion/` and temporary directories.

Do not use or modify real `incoming/` data in unit tests.

Canonical raw inputs live under `incoming/wall_<id>/`.
Generated intermediates live under `offline/work/wall_<id>/`.

V1 reconstruction paths are a historical record only. Do not modify V1.
