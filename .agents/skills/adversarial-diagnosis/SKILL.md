---
name: adversarial-diagnosis
description: Independently review a Hack the World branch or diff for scope, trust-boundary, verification, repetition, and user-facing regressions before release.
---

# Adversarial Diagnosis Review

Use for branch reviews, milestone audits, or requested regression reports.
Do not activate as a mandatory redesign pass for every small edit.

## Authority

1. Current user instructions.
2. `docs/PROJECT_RULES_AND_GUIDANCE.md`, `HACKATHON_SCOPE.md`, `docs/architecture.md`.
3. Source code and tests.
4. This skill.

Project canon and explicit user approvals override this skill. Never
reopen settled direction merely because a review skill is available.

## Procedure

1. Read the task scope and base/target refs. Inspect the full diff
   **before judging**, then load the affected contracts and existing tests.
2. Confirm every changed path is inside the authorized scope. Check
   protected areas: `diagnostic_core/` verification rules,
   `MODEL_ACTION_FIELDS` vs trusted-ingestion separation, budget
   accounting, and evidence provenance. Do not rebaseline a guard
   merely to make it pass.
3. Verify source evidence for each concern. A search hit, summary, or
   memory is navigation, not a finding. Open the code and test bodies.
4. Consult the review matrix only for changed subsystems:

   | Changed area | Review/test evidence |
   | --- | --- |
   | `diagnostic_core/` | contracts, engine transitions, verification tests |
   | Agent loop/providers | allowlist blocking, structural vs semantic failures, budget caps |
   | `phone_app.py` UI | honest states, real timeline data, no fabricated content |
   | `history_store.py` | ordering, archive honesty, photo-byte exclusion |
   | E2E/CI | deterministic fixture, gate wiring, honest not-run labels |

5. Run the smallest relevant checks. Report exact commands, results, and
   any prerequisite preventing execution. A passing unit suite does not
   prove browser behavior, voice behavior, or device feel.
6. Report severity-ordered findings with file/location, reproducible
   trigger, observed consequence, supporting evidence, and a bounded
   suggested correction. Order: confirmed defects first, then coverage
   gaps and manual risks. Say plainly when no actionable finding exists.

## Rules

- Do not edit production code during an independent review. A separate
  fix request needs its own authorization and stays limited to it.
- Do not elevate personal taste, absent optional tooling, or deferred
  features into blockers for a deliberately bounded milestone.
- Do not invent successful validation. Distinguish observed facts,
  reproduced failures, and missing coverage from each other.
