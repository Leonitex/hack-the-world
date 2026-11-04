---
name: browser-acceptance
description: Run real-browser acceptance testing of the Hack the World technician UI against scripted user flows, reporting observed behavior and honest not-run gates.
---

# Browser Acceptance Testing

Use for milestone acceptance, release gates, or requested end-to-end
verification. Do not claim browser behavior from unit tests alone.

## Authority

1. Current user instructions.
2. `docs/PROJECT_RULES_AND_GUIDANCE.md`, `HACKATHON_SCOPE.md`, `tests/e2e/README.md`.
3. Observed browser behavior, traces, and screenshots.
4. This skill.

## Procedure

1. Confirm prerequisites before claiming anything: Playwright with a
   real Chromium build installed, the app server running with the
   deterministic E2E provider fixture (`HTW_E2E_FAKE_PROVIDER=1`, never
   live keys), and a reachable local URL. If any prerequisite is
   missing, label the gate NOT-RUN with the exact setup step — never
   substitute unit-test results.
2. Execute the scripted user flows from `tests/e2e/`: problem intake,
   first diagnostic test, real-result submission, a meaningfully
   different follow-up test, history survival across page reload, and
   error/retry recovery. Voice, microphone, and camera steps run only
   where the browser profile genuinely supports them.
3. Capture evidence for every flow: pass/fail, the exact command, and
   trace or screenshot paths for failures. A flow that was not executed
   is NOT-RUN, not passed.
4. Judge against real user impact: can a technician complete the
   acceptance sequence in `docs/RELEASE_GATE.md` without confusion,
   loss, or fabricated content? Cosmetic polish never outranks a broken
   flow.
5. Record results in `docs/RELEASE_GATE.md`: gate name, verdict, date,
   environment (browser/build/OS), evidence paths, and remaining manual
   gates (physical device, real microphone, demo recording).

## Rules

- Never invent a passing browser run. Distinguish observed passes,
  reproduced failures, and blocked/not-run gates.
- Never use live model keys in automated browser runs. The deterministic
  fixture is the only provider for E2E.
- Do not edit production code while testing. File findings for a
  separately authorized fix; keep the failing evidence.
- Do not mark a milestone complete while a required gate is failing or
  silently skipped.
