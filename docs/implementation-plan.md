# Implementation Plan

## Milestone 1 — Diagnostic Core + Verification

Build the provider-independent session engine and non-skippable reliability rules first.

Deliverables:
- session schema and statuses;
- evidence ledger with stable IDs/provenance;
- hypothesis model and state transitions;
- provider-independent diagnostic tool contracts;
- `needs_input` handoff state;
- deterministic verification gates for confirmation/completion;
- bounded turn/completion-attempt semantics;
- deterministic local tests with no network access.

Acceptance criteria:
- a session can start from a symptom;
- at least two hypotheses can coexist;
- new evidence can strengthen, weaken, eliminate, or support hypotheses;
- invalid evidence references are rejected;
- a confirmed hypothesis/recommendation cannot bypass verification;
- insufficient evidence can produce a resumable `needs_input` state;
- repeated failed completion attempts cannot loop forever;
- tests run locally without network access.

## Milestone 2 — Meta Agent Loop

Connect the diagnostic core to one eligible Meta model route using the current Meta tool-calling pattern.

Primary hosted target: `muse-spark-1.3` through Meta Model API when billing/API access is ready. Open-weight partner adapters remain optional follow-ons.

Deliverables:
- provider adapter interface;
- tool/function schemas derived from Milestone 1 contracts;
- model-decides → code-executes → result-returns loop;
- bounded turn/retry handling;
- persistence/resume behavior;
- validation before any model output mutates session state;
- local test harness with mocked/recorded provider responses.

Acceptance criteria:
- the model chooses among valid diagnostic tools rather than following a hard-coded demo path;
- provider failures do not corrupt the session;
- real tool results are returned to the model before the next decision;
- verification gates remain outside the model's control;
- the adapter can be swapped without changing diagnostic state logic.

## Milestone 3 — Judge-Facing Demo UI

Create a focused web interface for the primary scenario as soon as the first agent loop works.

Deliverables:
- symptom input;
- image upload path;
- operational timeline (`observe` / action / result, without exposing private chain-of-thought);
- evidence timeline;
- hypothesis panel;
- next diagnostic step;
- `needs_input` handoff/result input;
- verification/refusal feedback where useful;
- final evidence-backed recommendation.

Acceptance criteria:
- a judge can understand the diagnostic state without reading logs;
- uncertainty and hypothesis changes are visible;
- at least one model-selected diagnostic action changes the state;
- at least one completion/recommendation passes a visible verification path;
- the primary scenario can be completed end to end comfortably inside the 3-minute demo.

## Milestone 4 — Visual Grounding

If it materially improves the primary demo, integrate SAM 3.1 for component localization/segmentation.

Acceptance criteria:
- SAM is invoked only where grounding helps a diagnostic action;
- grounding supports the investigation rather than acting as a standalone image analyzer;
- the UI makes the grounded region useful to the user.

## Milestone 5 — Optional Expansion

Only after the primary demo is stable, consider:
- Muse Voice Transcribe / voice-first evidence capture;
- hosted Muse Spark Open through an approved partner;
- provider failover;
- additional troubleshooting scenarios;
- richer evaluation datasets.

## Milestone 6 — Demo Hardening + Submission

Deliverables:
- scripted but genuine primary scenario;
- local validation log;
- failure-state cleanup;
- three-minute recording rehearsal;
- README architecture/model-use update;
- explicit new-work boundary in demo/submission;
- public repo/video/submission accessibility check.

## Build priority rule

For every feature ask:
1. Does it improve Impact, Meta tooling use, Technical Depth, or Demo quality?
2. Will a judge be able to see or verify the value within the submission artifacts?
3. Is it more valuable than hardening the current end-to-end demo?

If not, defer it.

## Workflow Constraint

Do not create or trigger GitHub Actions workflows. Development and validation are local-first, with Codex used where helpful for implementation and tests.