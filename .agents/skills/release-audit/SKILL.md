---
name: release-audit
description: Perform an independent release audit of Hack the World with a scoped verdict, execution truth, and explicit limits before any milestone is declared complete.
---

# Independent Release Audit

Use before declaring a milestone complete or approving a release
candidate. The auditor reviews; authors fix under separate authorization.

## Authority

1. Current user instructions.
2. `docs/PROJECT_RULES_AND_GUIDANCE.md`, `HACKATHON_SCOPE.md`, `docs/RELEASE_GATE.md`.
3. Source code, tests, and observed check output.
4. This skill.

## Procedure

1. State independence up front: what the auditor authored on this
   branch (if anything), what is under review, and which role or worker
   performs the audit. A reviewer cannot independently approve their
   own implementation; disclose role reuse instead of implying a fresh
   reviewer.
2. Verify execution truth for every claimed check: who or what ran it,
   the exact command, the observed result, and its date. A registry
   entry, task ticket, or plan is not evidence of execution. Re-run the
   cheapest decisive checks rather than trusting summaries.
3. Challenge the release claims one by one: diagnostic correctness on
   new turns, trust boundaries, verification determinism, budget
   behavior, history honesty, UI truthfulness, and error recovery.
   Record each as confirmed, contradicted, or unverified — with the
   file, test, or observation behind it.
4. Review open gates from `docs/RELEASE_GATE.md`: unit suite, browser
   acceptance, voice/device manual gates, and live-model smoke. A gate
   that did not run stays NOT-RUN; it never silently becomes a pass.
5. Deliver a scoped verdict: GO, CONDITIONAL GO, or NO-GO, naming the
   exact scope it covers (for example, "unit-tested logic only" vs
   "full user acceptance"). List blockers with severity, location, and
   recommendation, then explicit limits: what was not tested and what
   would change the verdict.

## Rules

- Do not edit production code, tests, or history during the audit. The
  only permitted write is the audit report itself.
- Do not self-certify the absence of risk without evidence. Unknowns
  stay unknown until a check or a physical test resolves them.
- Do not approve a release candidate while a required gate fails or a
  known user-facing defect is open.
- Record the verdict, evidence, and limits in `docs/RELEASE_GATE.md`
  so the next session inherits facts, not impressions.
