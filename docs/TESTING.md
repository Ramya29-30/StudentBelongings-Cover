# Testing and verification status

## Baseline reported by the v4 handover

The v4 handover records the following results from its Linux build environment (Python 3.12, Node 22) on 2026-11-09:

- Backend: **305 passed, 0 failed**, run in four groups.
- Frontend: TypeScript type-check passed; Vitest **28 passed**; production build succeeded.
- SQLite migration: a copy of the supplied revision-0005 database upgraded to revision 0006; integrity and foreign-key checks passed; original database hash was unchanged.
- Live smoke test: API readiness, built frontend, admin login, evidence-review queue/detail and analytics responded successfully.

These are the results reported in `PROJECT_HANDOVER.md` section H; they were not rerun in this continuation environment.

## Current v4 browser journey

`e2e/tests/v3.spec.ts` has been updated to exercise the current v4 workflow:

1. Create a student account and register a laptop with front/back photographs and an invoice.
2. Confirm that policy purchase is blocked while evidence is pending.
3. Sign in as administrator and approve the registration evidence.
4. Sign back in as the student and purchase a simulated policy.
5. Submit a claim in development simulation and confirm that the report is labelled as simulated and that the claim waits for staff confirmation rather than being automatically paid.

The Playwright suite has **not yet been executed** in this environment. It requires Node.js 20+, `npm ci` in `e2e/`, and an installed Chromium browser. The test server uses a throw-away database and `AI_VERIFY_MODE=dev_simulation`; this verifies workflow plumbing, not damage-detection accuracy.

## Continuation environment checks

The available Python runtime here is Python 3.13, not the project's specified Python 3.12. The first full pytest collection stopped because the development-only `onnx` package was unavailable. Installing it was not possible because this environment has no package-network access. A partial pytest run also exceeded the available execution window. Therefore **no new passing test count is claimed for this continuation**.

For a valid local run on Windows, use Python 3.12 and the supplied scripts:

```bat
run-tests.bat
run-e2e.bat
```

For Playwright, `run-e2e.bat` installs the browser and dependencies. If browser installation is blocked, record the E2E suite as not run rather than treating it as passed.

## AI model validation status

- `backend/models/yolo11n.onnx` is the bundled object detector; it is not a damage classifier.
- `backend/models/damage_model.onnx` is **not present** in the v4 ZIP.
- No real damage model has been trained or evaluated. Damage metrics must remain **Not measured**.
- Device-matching thresholds have not been calibrated on real device photographs.
- Development simulation assumes damage from the claim form and must be described as simulation.

## Not yet verified

- Playwright browser suite and manual UI journey on Windows.
- Real damage-model training, ONNX export and test-split evaluation.
- Real-photo device-match calibration and false-positive analysis.
- Live vision-language provider calls.
- PostgreSQL migration, Docker build, accessibility scan, penetration test and load test.

Do not report any of these as complete until the corresponding command or review has actually been run and its output retained.
