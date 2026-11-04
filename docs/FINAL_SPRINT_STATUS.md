# Final Sprint Status (M3 / M4 / M5)

Branch: `work/final-hackathon-sprint`, based on `origin/work/phone-mvp`.
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
