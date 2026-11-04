# Browser E2E for Hack the World

Deterministic end-to-end tests driven by Playwright against a local app
server running the scripted fake provider. No live model keys are used.

## Setup (once per machine)

```sh
cd tests/e2e
npm install
npx playwright install chromium
```

## Run

Terminal 1 — start the app with the deterministic fixture:

```sh
cd <repo-root>
# Windows PowerShell:
$env:HTW_E2E_FAKE_PROVIDER = "1"
python phone_app.py
```

Terminal 2 — run the suite:

```sh
cd tests/e2e
npx playwright test
```

`E2E_BASE_URL` overrides the default `http://127.0.0.1:8000` when the
server runs on another host or port.

## What the gates prove

- `technician completes two distinct diagnostic turns`: intake renders,
  the first scripted test appears, a submitted result advances the same
  session to a *different* follow-up test, and both the old instruction
  and the user result remain in the timeline.
- `history survives a page reload`: the current test and timeline
  persist across a reload.

## Constraints (read before extending)

- Workers are serial (`workers: 1`): the demo server holds one global
  session, so parallel tests would corrupt each other's state.
- Never run these specs against a server with live keys: the assertions
  expect the exact fixture script from `agent/factory.py:e2e_script`.
- Voice, microphone, camera, and physical-device behavior are manual
  gates; Playwright here covers scripted DOM flows only.
