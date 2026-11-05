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
- `an answered test is never asked twice` (`repeat-guard.spec.js`):
  against a problem containing `e2e-repeat`, the scripted model re-asks
  an answered test verbatim; the app blocks it, presents a distinct
  follow-up, and keeps the first instruction in the timeline exactly
  once.
- `unfinished cases switch, solve, and reopen without losing context`
  (`reopen-case.spec.js`): two cases stay open, switching preserves the
  pending test plus evidence and hypotheses, technician solve/reopen
  round-trips with audit entries, and the pending test survives.

## Constraints (read before extending)

- Workers are serial (`workers: 1`): the demo server is shared state,
  so parallel tests would corrupt each other's cases.
- A shared `beforeEach` resets through the UI ("Start a new
  investigation") before each test; never assume a fresh server, since
  each test leaves its cases behind.
- Re-runs need a wiped database plus a server restart (`rm
  data/history.db`, then restart the fixture server); otherwise earlier
  cases with the same problem text break strict-mode selectors.
- Never restart the server mid-run: the fixture scripts are exact-fit
  per case, so a restart replays them against restored state. Restart
  recovery is proven by the Python suite (`AppCaseTests`), not here.
- Never run these specs against a server with live keys: the assertions
  expect the exact fixture script from `agent/factory.py:e2e_script`.
- Voice, microphone, camera, and physical-device behavior are manual
  gates; Playwright here covers scripted DOM flows only.
