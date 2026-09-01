# Gate-aware wall build — run lifecycle

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

Phase 1 plus approved Generic Stage 2 does **not** mean unattended production through FIELD_TEST_READY. Stage 3 / route production remain locked.

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

Approved production `./rockvision build` may execute:

- DISCOVERY
- PREFLIGHT
- INGEST
- QUALIFY
- STAGE 2 SELECTION (one frozen `select_stage2_inputs` result)
- HEIGHT / VERTICAL DATUM GATE
- POSITIONING QUALITY GATE
- RECONSTRUCTION (generic selected sources only)
- METRIC REGISTRATION (same sources + reconstruction-time provenance)

It does not call legacy reconstruct/register without selected sources.
It does not call reference-match, pnp, DXF coordinate conversion, or route package build.

Multiple capture / MRK / metadata / model candidates remain inventory during discovery. Generic Stage 2 selection uses the approved selection contract; it does not invent a wall-id special case.

Individual walls still fail closed on data/evidence gates (for example current Jinshidong data is `POSITIONING_QUALITY_NOT_PROVEN` and must not launch reconstruction).

## TERMINATE

Any of `AUTO_FAIL`, `HUMAN_REVIEW_REQUIRED`, or `DEVELOPMENT_GATE_REVIEW_REQUIRED` writes reports, rechecks the input freeze, and ends the run.

There is no “wait / edit incoming / continue” on the same run. Changed input requires a new `runId`.

`FIELD_TEST_READY` keeps its real product meaning. Phase 1 reports it as `NO`.
