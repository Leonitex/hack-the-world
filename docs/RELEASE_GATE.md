# Release Gate (Issue #10)

No milestone is complete and no release candidate is approved until every
required gate below is green or explicitly labeled NOT-RUN with its
blocker. A gate that did not run never silently becomes a pass.

## Agent roles

| Role | Driven by | Owns |
| --- | --- | --- |
| Adversarial reviewer | `.agents/skills/adversarial-diagnosis` | scoped diff review, severity findings |
| Browser runner | `.agents/skills/browser-acceptance` | Playwright E2E execution and evidence |
| Release auditor | `.agents/skills/release-audit` | independent verdict and limits |

Execution uses Muse Code native subagents. A spawn record is not proof
of work: every agent result must arrive as a readable result envelope
whose claims (files, lines, commands, outputs) the coordinator
spot-checks before recording. Third-party agent frameworks are out of
scope unless separately verified.

## Gates

| Gate | Required for | How it runs |
| --- | --- | --- |
| Unit suite | every milestone | `python -m unittest discover -s tests` |
| Compile checks | every milestone | `compileall` over `agent diagnostic_core examples tests history_store.py phone_app.py` |
| Skill validation | skill changes | `muse skills validate .agents/skills/<id> --json` |
| E2E spec check | E2E changes | `node --check` on `tests/e2e/*.js` |
| Browser E2E | release candidate | Playwright smoke vs fixture server (see `tests/e2e/README.md`) |
| Live-model smoke | release candidate | `python live_m6c_smoke.py` where `MODEL_API_KEY` is set |
| Voice/device manual | release candidate | human: mic, read-aloud, photo, Galaxy A17 |

## Latest results

<!-- Updated by each release audit. Dates are UTC. -->

| Gate | Verdict | Date | Evidence / notes |
| --- | --- | --- | --- |
| Unit suite | PASS | 2026-11-04 | `python -m unittest discover -s tests`: 182 tests OK (includes 3 E2E-fixture tests) |
| Compile checks | PASS | 2026-11-04 | `compileall` over `agent diagnostic_core examples tests history_store.py phone_app.py`: clean |
| Skill validation | PASS | 2026-11-04 | `muse skills validate --json`: `valid: true`, zero diagnostics, all 3 skills |
| E2E spec check | PASS | 2026-11-04 | `node --check` on config + spec; `package.json` + `package-lock.json` (Playwright 1.64.1) parse |
| CI workflow | PASS (static) | 2026-11-04 | `qa-gates.yml` parses; unit + e2e jobs defined; not yet executed by a runner |
| Browser E2E | PASS | 2026-11-04 | Run 41934858433: 2 passed (3.8s), Chromium, serial workers, fixture server |
| Live-model smoke | NOT-RUN | 2026-11-04 | No `MODEL_API_KEY` in automation env; run `live_m6c_smoke.py` in a keyed window |
| Voice/device manual | NOT-RUN | 2026-11-04 | Requires human + Galaxy A17; never waived silently |

Independent subagent review (2026-11-04, native worker, read-only)
confirmed scope, found 2 High findings, both fixed and re-verified:
`HTW_E2E_FAKE_PROVIDER` fixture text tripped the scenario-token guard
(reworded, suite green), and CI used `npm ci` with no lockfile
(lockfile generated and pinned). Protected areas (`diagnostic_core/`,
trust boundary, budgets, provenance) verified untouched; no secrets
found; E2E selectors cross-checked against templates.

CI run 41928015974 failed on cross-test coupling (test 2 assumed a fresh
form while the single-session server still held test 1's session). Fixed
with a shared UI-reset `beforeEach` plus a settle wait — no assertions
weakened, no fixture changes — and re-verified green in run 41934858433.

## Pending coordination with issue #9

Issue #9 (`work/nonrepeating-diagnosis`, not yet branched as of
2026-11-04) will add repeat-guard and case-reopen behavior. When it
lands, extend `tests/e2e/` with:

- `repeat-guard.spec.js`: submit the same observation twice through the
  UI; assert the second diagnostic test differs from the first and the
  first instruction remains in the timeline.
- `reopen-case.spec.js`: start an investigation, leave it unfinished,
  open it from the history archive, and continue it; assert context
  (evidence, hypotheses, pending test) is preserved.

Activate these specs only against a server running the #9 features;
until then this section stays pending and the browser gate covers the
smoke flow above.

## Running the automated gates locally

```sh
python -m unittest discover -s tests
python -m compileall -q agent diagnostic_core examples tests history_store.py phone_app.py
muse skills validate .agents/skills/adversarial-diagnosis --json
muse skills validate .agents/skills/browser-acceptance --json
muse skills validate .agents/skills/release-audit --json
node --check tests/e2e/playwright.config.js
node --check tests/e2e/smoke.spec.js
```

Browser E2E additionally needs `npm install` plus
`npx playwright install chromium` inside `tests/e2e`, and the app
server running with `HTW_E2E_FAKE_PROVIDER=1` (see
`tests/e2e/README.md`).
