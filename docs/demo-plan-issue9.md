# Demo Plan — Issue #9: Non-Repeating Diagnosis & Reopenable Cases

Branch: `work/nonrepeating-diagnosis`. All behaviors below passed automated
verification (255 unit tests, 4 browser tests). No model responses are quoted;
the plan describes behavior classes the gates prove.

## Setup (pick one mode)

**Mode A — deterministic (recommended for recording):**
```sh
HTW_E2E_FAKE_PROVIDER=1 python phone_app.py
```
Fixed fixture scripts; every beat below reproduces exactly.

**Mode B — live model:** set `MODEL_API_KEY` (or `BASETEN_API_KEY`) and run
`python phone_app.py`. The model chooses freely; the repeat guard,
inconclusive close, and case lifecycle still apply, but exact questions vary.
Live behavior was NOT verified in automation (no key in the test
environment); rehearse once before recording.

## Script (~5 minutes)

### 1. Start an investigation (0:00–0:45)
Enter: "Phone shows no response when the power button is pressed."
Show: evidence chip `e1`, proposed causes, first test in "Do this next".

### 2. Answer; the assistant never repeats (0:45–2:00)
Answer: "No LED, no fan, nothing at all."
Show: answer recorded as evidence linked to the test; the NEXT test is a
different check (fixture: indicator light, then fan noise, then charging
port). State the guarantee: answered tests are blocked verbatim,
near-duplicate, padded, cross-kind, and homoglyph variants included.

### 3. Two cases stay open (2:00–3:00)
Start a second case ("Second device is silent"). Show both badges `open` /
`awaiting result`. Open the first case again: pending test, evidence, and
hypotheses intact; answer to continue. No case closed implicitly.

### 4. Honest stop, not a forced answer (3:00–3:45)
If the model runs out of distinct safe tests, show the "Inconclusive
handoff" card: what was checked (with evidence count), what remains
possible, safe next steps. Explicitly not a verified diagnosis.

### 5. Technician closes and reopens (3:45–4:45)
"Mark solved" with a repair note; show the solved badge and audit entry.
Further answers are refused while solved. "Reopen case": investigation
continues with prior records intact (recommendation kept if one existed).

### 6. Restart proof (optional, 4:45–5:15)
Stop and restart the server (same `HTW_HISTORY_DB`), open the case from
Investigations: same session, trajectory, budgets, and timeline restored.
Checkpoint corruption degrades to read-only history, never a crash.

## Evidence map

| Beat | Proven by |
|---|---|
| Never repeats | `DuplicateGuardTests` (8), `repeat-guard.spec.js` |
| M8D scenario | `test_m8d_acceptance_scenario` |
| Honest inconclusive | `InconclusiveCoreTests`, `AutoInconclusiveTests`, handoff UI test |
| Switch/solve/reopen | `AppCaseTests` (16), `reopen-case.spec.js` |
| Restart restore | `CheckpointTests`, `BookkeepingTests`, restart AppCaseTests |
| No secrets in store | `test_checkpoint_holds_no_secrets_or_photos` |
