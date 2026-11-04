# Final Sprint Status (M3–M7)

Branch: `work/final-hackathon-sprint`, based on `origin/work/phone-mvp`.
Follow-up branch: `work/final-polish-followup` (issue #6: M6A/M6B/M6C).
Milestone 7 branch: `work/persistent-history-cinematic-ui` (7A–7E).
Trust core preserved: `diagnostic_core/` and the `AgentLoop` validation
architecture are unchanged from the Milestone 2A checkpoint. All pre-existing
Milestone 1/2 tests still pass.

## M3 — Dependable Meta-backed diagnosis: DONE

What works:
- Baseten route (proven): `finish_reason=length` truncation now fails
  clearly instead of parsing garbage; HTTP/network/timeout errors map to
  `ProviderError`; token budget raised to 2000 for reasoning headroom;
  outbound tools proven to exclude trusted ingestion actions.
- Meta Model API route: the Milestone 2B1 adapter is integrated
  (stateless requests, `tool_choice=auto`, one call per turn requested,
  structured 400 details surfaced without secrets) plus new image support
  so photos reach Muse Spark on either route. Fully covered by mocked tests.
- Provider selection: `HTW_PROVIDER=auto|meta|baseten`. Auto prefers the
  proven Baseten route when `BASETEN_API_KEY` is present, else Meta Model
  API when `MODEL_API_KEY` is present. The UI badge shows the active route.
- Photo pipeline: initial and follow-up photos reach the model; uploads
  pass extension, MIME, magic-byte, and 8MB checks; each photo is
  associated server-side with its real evidence ID; follow-up photos
  update what the model sees next.
- Failure UX: browser shows safe messages only (full detail stays on the
  server console); sessions survive provider errors; a Try-again button
  continues the same session with a fresh provider budget.
- Server binds `127.0.0.1` by default; `HTW_HOST` overrides for LAN/phone testing.

Tests: 134 total green (`test_core` 45, `test_agent_loop` 31,
`test_meta_provider` 25, `test_baseten_provider` 12, `test_factory` 8,
`test_phone_app` 13). Live smoke NOT run: no credential is present in the
automation environment. Manual smoke: set `MODEL_API_KEY` or
`BASETEN_API_KEY`, activate `.venv`, run `python live_agent_loop_probe.py`
(max 6 decisions, read-only).

Blockers: full Meta Model API tool-loop compatibility is unverified live
(an earlier live 400 motivated the error-mapping work). Baseten remains
the reliable demo default for that reason.

Deviation from the issue: auto-selection prefers Baseten (proven) with
Meta as fallback, rather than Meta-first with Baseten as backup. Reason:
demo reliability; the issue itself says not to block launch on direct
Meta API compatibility. Explicit `HTW_PROVIDER=meta` is fully supported.

## M4 — Hands-free technician UI and orb: DONE (code + tests; device/browser acceptance manual)

Built on `565fd3a` (orb, read-aloud, dictation, verification display).
Added: red error orb state with 4s auto-recovery (recognition/speech
failures, server-error pages), microphone permission indicator via
`navigator.permissions`, `aria-live` assistant bubble + `role=status`
voice note + mic `aria-label`, desktop breakpoint (860px) + mobile
styles + `prefers-reduced-motion`, per-evidence source/provenance in
expandable chips. Hypothesis badges show only genuine core statuses —
no fake high/medium/low rankings anywhere.

Tests: 136 total green (`test_phone_app` 15, +2 M4 UI pins). Manual
acceptance still required: full device conversation, PC-browser cycle
with image upload, model-chosen next test spoken end to end.

## M5 — Test, polish, and demo handoff: DONE (code + docs; live/manual acceptance remains)

Polish: `.env.example` documents the exact supported surface
(`HTW_PROVIDER`, `MODEL_API_KEY`, `META_MODEL_API_KEY`, `META_MODEL_ID`,
`META_BASE_URL`, `BASETEN_API_KEY`, `HTW_HOST`, `PORT`) and drops dead
Modal/Fireworks entries; `docs/phone-mvp.md` gains the provider-selection
note and a branch-durable clone command. No code changes in M5.

Final validation: 136 tests green
(`test_core` 45, `test_agent_loop` 31, `test_meta_provider` 25,
`test_baseten_provider` 12, `test_factory` 8, `test_phone_app` 15),
`compileall` clean, `git diff --check` clean, zero `SyntaxWarning`s.
`diagnostic_core/` untouched since the Milestone 2A checkpoint.

Launch for the final manual test (PowerShell):

```powershell
cd C:\Users\Scott\hack-the-world
git checkout work/final-hackathon-sprint
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:BASETEN_API_KEY = "<hackathon key>"   # or MODEL_API_KEY + HTW_PROVIDER=meta
python phone_app.py
# open http://127.0.0.1:8000
```

Manual acceptance still required: live provider smoke (no credential in
automation env), full device conversation, PC-browser cycle with image
upload, model-chosen next test spoken end to end, three-minute demo
recording per `docs/demo-plan.md`.

Blockers: none in code. Live Meta tool-loop compatibility is still
unverified (Baseten is the reliable demo default); `gh` CLI is not
installed, so the PR is opened via the web UI.

## M6A — Fix follow-up progress (issue #6 P0): DONE (code + tests; live proof manual)

Root cause confirmed by test repro: `AgentLoop` kept a lifetime
`max_provider_steps=14`, so `/resume` + `run()` on the same loop
returned `BUDGET_EXHAUSTED` with zero new provider calls (the failing
test showed "14 not greater than 14"). The page then rendered
hypotheses with no next action — the reported stall.

Fix: each `run()` call gets a bounded `max_advance_steps` allowance
within a session-wide `max_provider_steps` cap (app: 14 per round, 60
total). Spending one advance returns recoverable `ADVANCE_EXHAUSTED`;
spending the session cap returns `BUDGET_EXHAUSTED`. `/retry` reuses the
same loop, so feedback and spend carry over and retries cannot bill
forever. `LoopResult.advance_steps` reports per-round steps; the UI
shows outcome + round/total steps + a "New evidence recorded →
reassessed" note after every resume.

Meta zero-tool replies: `MetaProvider.decide()` now retries text-only
replies against a bounded reinstruction (default 2 retries, with the
last `finish_reason` in the diagnostic) and raises `ProviderError`
instead of returning an empty decision that burned loop steps. Plain
text is never executed or stored as evidence.

Tests: 147 total green (+4 loop, +3 meta, +4 app), including resume
after a fully spent advance, 2nd/3rd user turns, structural-error
double-cap accounting, persistent text-only boundedness, same-session
retry, and session-cap start-over guidance.

## M6B — Premium technician UX (issue #6 P1): DONE (code + tests; browser/device acceptance manual)

Single-file redesign, no new dependencies or external assets: inline
SVG orb (layered plasma core, segmented arcs, orbiting scan markers,
particles, energy sweep, red error core) with
idle/listening/thinking/speaking/error states on GPU-friendly
transforms; desktop 3-zone layout (timeline / assistant / technical)
collapsing to one mobile flow; a real conversation timeline derived
only from snapshot diffs + user inputs (session start, evidence,
causes, status changes, test requests, verified recommendation — each
quoting a real record id); voice controls (Hear/Stop/Hands-free, mic
permission indicator, dictation fallback); one prominent next action;
double-submit guard with Working state; draft preservation on
start/resume errors; error-card keyboard focus;
`prefers-reduced-motion` support; `aria-live` announcements kept.

Tests: 151 total green (+4 app: timeline lineage, assistant hooks,
draft preservation ×2). JS passes `node --check`; real HTTP smoke
`GET / → 200` with orb + hero verified on port 8123.

## M6C — True acceptance (issue #6): BLOCKED live, manual steps pending

Automated gates green: 151 tests, `compileall` clean,
`git diff --check` clean, `diagnostic_core/` untouched.

Live Meta 2–3-turn smoke: BLOCKED from this shell — no `MODEL_API_KEY`
/ `META_MODEL_API_KEY` is inherited here and no `.env` file exists, so
no live call was made and none is claimed. Run in the window where the
key is already set (never print it):

```powershell
cd C:\Users\Scott\hack-the-world
git checkout work/final-polish-followup
.\.venv\Scripts\Activate.ps1
python live_m6c_smoke.py
```

Bounded: 18 steps total, 6 fresh steps per round, 30s Meta timeout.
Prompt 1 defaults to the issue's suggested result (labeled); prompt 2
is optional. The script prints PASS/FAIL per round, including "real new
model decision after Submit" — the issue #6 acceptance gate.

App launch for the manual browser test:

```powershell
cd C:\Users\Scott\hack-the-world
git checkout work/final-polish-followup
.\.venv\Scripts\Activate.ps1
python phone_app.py
# open http://127.0.0.1:8000 (MODEL_API_KEY already set in that window)
```

Still needs a human: the live smoke above; read-aloud, mic
permission/text fallback, photo upload, and error/retry recovery on
desktop Chrome/Edge; a Samsung A17 orb/layout check; the three-minute
demo recording.

## M7A — Persistent investigation history: DONE (code + tests)

New `history_store.py` (stdlib sqlite3, `data/history.db`, overridable
via `HTW_HISTORY_DB`): session rows with auto-names plus per-session
sequenced event rows with UTC timestamps, written atomically alongside
the in-memory timeline. Starting or resetting archives the previous
session instead of deleting it; a startup sweep marks sessions from
older processes as read-only archives, so a restart never presents a
dead session as resumable. Sessions list with live/archived badges,
rename, and a read-only archive view with full timelines. Photo bytes
are never persisted — only a "shown this round, not stored" marker with
the real record id.

Tests: 11 store tests (ordering, reopen persistence, sweep, archive,
rename, isolation) + 7 app tests (archive-on-new, read-only view,
memory/DB parity, restart reopen, photo privacy, rename, unknown id).

## M7B/M7C/M7D — Cinematic UI: DONE (code + tests; browser/device acceptance manual)

Orb: fourth ring, inner plasma shimmer, dual orbiting markers,
thinking-only scanline, one-shot completed burst + lingering green
tint, word-boundary speech pulse (progressive enhancement), drifting
ambient background — all transform/opacity CSS, no new dependencies.
Bubbles: primary entrance animation plus the last two timeline entries
as reduced-emphasis bubbles linking to anchored timeline items, with
distinct user styling. Layout: mobile-collapsible history drawer that
stays open on desktop (CSS + `matchMedia` sync, no-JS safe),
status-colored hypothesis markers from real core statuses,
touch-action, and readable line height.

Tests: +10 app pins (orb layers, reduced motion, recents/anchors,
user styling, no pre-session recents, drawer, markers, polish, drawer
sync, rename escaping).

## M7E — Regression: green (live BLOCKED)

179 tests green, `compileall` clean, `git diff --check` clean, JS
`node --check` clean, HTTP smoke (`GET /`, empty `/start`, unknown
`/history/<id>`) all correct. `diagnostic_core/` untouched. Self-review
covered UX (drawer defaults, no-JS fallback), accessibility (live
regions, focus, labels, no color-only signals), security (rename
escaping proven, photo bytes excluded, API errors sanitized), and
performance (no blur/canvas animation loops; one-shot burst only).

Live Meta test: BLOCKED from this shell — no `MODEL_API_KEY` /
`META_MODEL_API_KEY` inherited, so no live call was made or claimed.
In the window where the key is set:

```powershell
cd C:\Users\Scott\hack-the-world
git checkout work/persistent-history-cinematic-ui
.\.venv\Scripts\Activate.ps1
python live_m6c_smoke.py
```

App launch:

```powershell
cd C:\Users\Scott\hack-the-world
git checkout work/persistent-history-cinematic-ui
.\.venv\Scripts\Activate.ps1
python phone_app.py
# open http://127.0.0.1:8000 (history persists in data/history.db)
```

Still needs a human: the live smoke; orb/bubble/drawer feel and voice
round-trip on desktop Chrome/Edge; the Samsung A17 check; multi-day
history retention spot-check; the demo recording.
