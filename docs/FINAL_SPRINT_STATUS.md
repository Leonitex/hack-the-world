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

## M4 — Hands-free technician UI and orb: PENDING

## M5 — Test, polish, and demo handoff: PENDING
