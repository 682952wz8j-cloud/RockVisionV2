# Phase 1 gate-aware wall build — run lifecycle

This is the Human handoff / run model for:

```text
./rockvision build <wall_id>
```

Fallback:

```text
python3 tools/rockvision.py build <wall_id>
```

Example:

```text
./rockvision build wall_jinshidong_01
```

Phase 1 does **not** mean unattended production through FIELD_TEST_READY.

---

## PREPARE

The program is not running.

Human:

1. Completes field capture, measurements, and external route authoring.
2. Copies every RockVision input for this wall into `incoming/wall_<id>/`.
3. Confirms wall membership. Nested device folders and original Unicode names are allowed. Human does not need technical subdirectories such as `DRONE_RAW/` or `ROUTES/`.

Human owns input preparation.

## START

Human runs `./rockvision build <wall_id>`.

START is the input-freeze boundary for that run.

Until the run TERMINATES:

- Human must not add, delete, modify, replace, rename, or move files under that wall incoming tree.
- RockVision does not write incoming.

`incoming/wall_<id>/` is read-only source evidence for the run.

## RUN

Each START creates a new `runId` and an input manifest (path, size, classification, SHA-256). Outputs go to:

```text
offline/work/<wall_id>/wall_build/<runId>/
```

Phase 1 may execute only:

- DISCOVERY
- PREFLIGHT
- INGEST
- QUALIFY

It does not call reconstruct, register, reference-match, or pnp.

Multiple capture / MRK / metadata / model candidates are inventory only. Phase 1 does not select them and does not ask Human to choose.

## TERMINATE

Any of `AUTO_FAIL`, `HUMAN_REVIEW_REQUIRED`, or `DEVELOPMENT_GATE_REVIEW_REQUIRED` writes reports, rechecks the input freeze, and ends the run.

There is no “wait / edit incoming / continue” on the same run. Changed input requires a new `runId`.

`FIELD_TEST_READY` keeps its real product meaning. Phase 1 reports it as `NO`.
