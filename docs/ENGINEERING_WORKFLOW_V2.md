# Engineering Workflow v2

Permanent repository workflow for ordinary development.

This file does **not** replace [`DEVELOPMENT_GATES.md`](DEVELOPMENT_GATES.md),
[`COORDINATE_CONVENTIONS.md`](COORDINATE_CONVENTIONS.md), height/datum
contracts, or any Gate PASS / FREEZE record.

Status source of truth for Stage/Gate progress remains [`README.md`](../README.md)
and the explicit Gate documents. This workflow only classifies *how* a task
is implemented and reviewed.

---

## Purpose

Future development uses **risk-based review**.

Do not repeat a full audit protocol on every task.
Do not convert ordinary work into a Gate without an explicit reason.

---

## Risk levels

Classify each task before implementation. If classification is ambiguous,
use the higher risk. An existing explicit Gate restriction always wins.

### R0 — Mechanical

Documentation, labels, formatting, comments, and other non-functional
changes that do not alter runtime behavior or contracts.

```text
implement → basic check → commit
```

### R1 — Local Code

Isolated code, tool, or UI changes that do not alter pipeline contracts,
shared serialization, or Gate semantics.

```text
implement → automated tests → checkpoint commit → review if requested
```

### R2 — Pipeline

Changes that affect pipeline behavior, state machines, ingestion,
matching, serialization, or shared interfaces.

```text
implement → tests/invariants → checkpoint commit → independent review
```

### R3 — Gate-Critical

Coordinate systems, metric scale, height datum, visual localization /
PnP, AR transforms / alignment, route geometry provenance, canonical
artifacts, or Gate PASS / FREEZE semantics.

```text
explicit protocol
  → implementation
  → evidence
  → checkpoint commit
  → independent review
  → correction if required
  → Gate closure
```

Cursor must not independently close a Gate. Gate closure is a human
decision after independent review.

---

## Permanent rules

1. Cursor may create local checkpoint commits unless a task explicitly
   forbids commits.
2. Cursor must not push unless explicitly authorized.
3. Cursor must not independently declare a Gate PASS, FREEZE a canonical
   artifact, or advance a Stage/Gate.
4. Existing coordinate, metric, height, provenance, and Gate contracts
   remain authoritative.
5. Risk classification never overrides an existing explicit Gate
   restriction.
6. Automated deterministic checks should replace repeated manual audit
   wherever practical.
7. After review failure, review only the corrective delta unless the
   failure invalidates the original evidence.
8. Ordinary development must not be converted into a Gate without an
   explicit reason.

---

## Classification guide

| Signal | Minimum risk |
|---|---|
| Markdown / comments / labels only | R0 |
| Isolated helper, CLI wrapper, UI copy, test-only fixture | R1 |
| Ingestion, qualification, selection, wall-build state, shared JSON | R2 |
| Frames, geodesy, Umeyama/RANSAC, Sim(3), height datum, PnP, AR, routes, PASS/FREEZE | R3 |

If a task mixes levels, execute the highest applicable workflow.

---

## `./rockvision verify`

Intended long-term command for automated deterministic checks.

```text
./rockvision verify
```

Fallback:

```text
python3 tools/rockvision.py verify
```

**This command is not a Gate PASS, FREEZE, or Stage advance.**

### Current status

**Partially implemented.** A thin wrapper aggregates existing Python
unit-test modules. It does not invent new algorithm checks and does not
change production behavior.

Current aggregation lives in `offline/verify.py` and is dispatched from
`tools/rockvision.py`.

### Existing checks that already feed verify

These modules are the current verify suite:

- `offline.tests.test_ingestion`
- `offline.tests.test_qualification`
- `offline.tests.test_colmap`
- `offline.tests.test_metric_registration`
- `offline.tests.test_height_enforcement`
- `offline.tests.test_stage2_selection`
- `offline.tests.test_stage2_terra`
- `offline.tests.test_stage2_rule_c`
- `offline.tests.test_stage2_regression`
- `offline.tests.test_wall_build_phase1`
- `offline.tests.test_wall_build_stage2`
- `offline.tests.test_reference_matching`
- `offline.tests.test_pnp`
- `offline.tests.test_localization_package`
- `offline.tests.test_stage3_run_binding`
- `offline.tests.test_localization_package_e2e`
- `offline.tests.test_publisher`
- `offline.tests.test_catalog_promotion`
- `offline.tests.test_engineering_workflow`

Several of those already encode production-lock and frozen-artifact
invariants (Phase 1 allowlist, Generic Stage 2 closed, Jiulongfeng
fingerprints, OpenCV pins). Verify only *runs* them. It does not
reinterpret their meaning.

### Missing checks (not in verify yet)

- iOS / Xcode unit and UI tests
- Physical iPhone field-session checks
- Standalone frozen-artifact hash CLI (today these live inside unit tests)
- Gate 5 route-package / renderer visual validation
- Any check that would require executing unapproved Stage 3 / route
  production on ordinary `./rockvision build`

Do not add those by expanding verify into a new framework in this file.
Add them later only as thin wrappers around already-authoritative checks.

### Proposed implementation order

1. Keep the current unittest aggregation as `./rockvision verify`.
2. Add missing *already-deterministic* checkers one at a time (pin
   verify, fingerprint verify) without changing algorithms.
3. Document iOS and physical checks as separate commands or manuals.
   Do not pretend they ran because `verify` passed.
4. Never let `verify` print or persist a Gate PASS / FREEZE.

---

## Relationship to Gates

- [`DEVELOPMENT_GATES.md`](DEVELOPMENT_GATES.md) remains sequential Gate
  process.
- Workflow v2 is for work that is *not* automatically a Gate.
- Opening or closing a Gate still requires an explicit protocol (R3).
- `GENERIC_STAGE2_PASS` = YES / CLOSED
- `PRODUCTION_BUILD_STAGE2_ENABLED` = YES

Ordinary `./rockvision build` executes approved Generic Stage 2
(selection, height, positioning quality, reconstruction, metric
registration). Individual walls still fail closed on data/evidence
gates. Stage 3 and route production remain locked. This document does
not rewrite historical Gate 0–11 chapters.
