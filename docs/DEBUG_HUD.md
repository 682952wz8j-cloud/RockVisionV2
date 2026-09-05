# Debug HUD scoping

**ACTIVE TEST PHASE OWNS THE DEBUG HUD.**

For each Gate / Phase field test, show only:

1. controls required to perform the current test
2. state required to understand current test progress
3. evidence required to determine PASS / FAIL

HUDs and controls that belong only to other Gates/Phases must be hidden
for the active test. Do not delete their implementation. Do not mix
historical diagnostic information into every field-test UI.

Do not solve overlap by shrinking text to an unreadable size, and do not
rely on screen rotation. Prefer a compact, vertically scrollable panel
when the active HUD can exceed screen height.

Semantic DEBUG modes (extensible, not a product UI architecture):

- `cloudD5` — Cloud catalog discovery / install
- `gate4b` — Gate 4B Physical Validation
- `stage3` — Stage 3 localization debug
- `stage5` — Stage 5 route debug

D5 Cloud discovery UI is DEBUG-only. It is not the permanent production
UI. Release continues to use the existing Gate 4B field-test surface.
