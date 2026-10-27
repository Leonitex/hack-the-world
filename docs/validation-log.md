# Validation Log

This file records meaningful local validation performed during the hackathon. GitHub Actions is intentionally not used for this project.

## Format

For each milestone, record:
- date/time;
- commit SHA;
- commands run;
- tests/checks passed or failed;
- manual demo notes;
- known limitations.

No validation claims should be added unless they were actually run and observed.

## Milestone 1 - Diagnostic Core + Verification

- Date: 2026-10-27, 21:29 UTC.
- Branch: `work/diagnostic-core` (existing branch, based on `29b4e97`).
- Commit: this entry is committed with the implementation; obtain its SHA with
  `git log -1 --format=%H -- docs/validation-log.md`.
- Environment: Windows PowerShell; Python 3.14.7. Minimum language version is
  Python 3.11; other interpreter versions have not been exercised here.
- Dependencies added: none.

Exact local validation commands run from the repository root:

```powershell
python -m unittest discover -s tests -v
python -m examples.no_display
python -m compileall -q diagnostic_core examples tests
git diff --check
```

Results:

- Unit tests: **41 passed, 0 failed, 0 errors**. Socket connection functions are
  patched to fail during every test; no network access or provider credentials
  are needed.
- Example: observed `needs_input -> investigating -> completed`, a passing
  verification result, a confirmed cable hypothesis, three weakened alternatives,
  and the recommendation to replace the failing cable.
- Compilation: passed, no output/errors.
- Whitespace check: passed, no output/errors.
- No test/runtime warnings observed. No Actions workflow was created, edited,
  enabled, or invoked. No provider calls, frontend, deployment, or model loop.
- Git staging reported Windows LF-to-CRLF working-copy conversion warnings for
  the new files. `git diff --cached --check` passed; these warnings do not change
  runtime behavior.

Implementation choices within the specification: in-memory sessions; insertion
order instead of timestamps; strict two-step reopening of eliminated hypotheses;
explicit links for resolving contradictions; terminal `paused` state on lifetime
budget exhaustion. Normal `needs_input` handoffs resume without resetting budgets.
No requested behavior was deferred. Persistence was not introduced, so no
persistence round-trip test applies.

Known limits: deterministic checks establish valid references and transitions,
not the truth/causal relevance of observations or free-text recommendations.
Provenance is descriptive rather than authenticated. The future application must
bind evidence-writing actions to actual user/tool results. State is in memory and
supports one synchronous caller; there is no durable restore or resume from a
budget-exhausted pause. See `diagnostic-core.md` for complete contracts.
