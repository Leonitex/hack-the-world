# Implementation Plan

## Milestone 1 — Diagnostic Core

Build the provider-independent session engine first.

Deliverables:
- session schema;
- evidence ledger;
- hypothesis model;
- state transitions;
- next-action contract;
- deterministic tests using mocked model outputs.

Acceptance criteria:
- a session can start from a symptom;
- at least two hypotheses can coexist;
- new evidence can strengthen, weaken, eliminate, or support hypotheses;
- a final recommendation cannot be marked confirmed without supporting evidence;
- tests run locally without network access.

## Milestone 2 — Meta Model Adapter

Connect the diagnostic core to one eligible Meta model route.

Deliverables:
- provider adapter interface;
- structured response schema;
- prompt/tool contract for observe → hypothesize → next test → verify;
- validation and retry/failure handling;
- local test harness with recorded/mock responses.

Acceptance criteria:
- model output is validated before entering session state;
- provider failures do not corrupt the session;
- the adapter can be swapped without changing diagnostic state logic.

## Milestone 3 — Demo UI

Create a focused web interface for the primary scenario.

Deliverables:
- symptom input;
- image upload path;
- evidence timeline;
- hypothesis panel;
- next diagnostic step;
- result input;
- final evidence-backed recommendation.

Acceptance criteria:
- a judge can understand the diagnostic state without reading logs;
- uncertainty and hypothesis changes are visible;
- the primary scenario can be completed end to end.

## Milestone 4 — Visual Grounding

If access/time permits, integrate SAM 3.1 or another eligible Meta visual capability for component localization.

Acceptance criteria:
- grounding supports a diagnostic action rather than acting as a standalone image analyzer;
- the UI makes the grounded region useful to the user.

## Milestone 5 — Demo Hardening

Deliverables:
- scripted but genuine primary scenario;
- local validation log;
- failure-state cleanup;
- three-minute recording rehearsal;
- README architecture and model-use update;
- public submission checklist.

## Workflow Constraint

Do not create or trigger GitHub Actions workflows. Development and validation are local-first, with Codex used where helpful for implementation and tests.
