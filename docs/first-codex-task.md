# First Codex Task — Milestone 1: Diagnostic Core + Verification

## Objective

Implement only the provider-independent diagnostic foundation described in `docs/architecture.md` and `docs/implementation-plan.md`.

This milestone must make the later Meta agent loop possible without coupling the core to any provider.

## Required behavior

### Session state
- Start a diagnostic session from a problem statement.
- Support session states at minimum: `investigating`, `needs_input`, `awaiting_verification`, `completed`, `paused`.
- Track bounded turn/completion-attempt counters or equivalent state needed to prevent infinite loops later.

### Evidence
- Add evidence items with stable IDs.
- Store source/provenance metadata (for example user text, diagnostic test, image observation, visual grounding).
- Reject references to evidence IDs that do not exist.

### Hypotheses
- Maintain multiple competing hypotheses simultaneously.
- Support hypothesis states: `possible`, `supported`, `weakened`, `eliminated`, `confirmed`.
- Link supporting and contradicting evidence IDs to each hypothesis.
- Do not hard-code the primary demo scenario into the state engine.

### Diagnostic actions / tool contracts
Define a small provider-independent command/tool surface suitable for a future model-driven loop. It should cover the concepts needed for:
- recording evidence;
- proposing/updating hypotheses;
- requesting a diagnostic test;
- recording a test result;
- requesting additional user evidence / entering `needs_input`;
- attempting to submit a final recommendation.

The implementation may choose clearer names/structures, but keep the surface small and generic.

Important: Milestone 1 does **not** implement a model loop. It defines and tests the contracts that a future Muse model will be allowed to invoke.

### Verification gates
A final confirmation/recommendation must pass application-owned checks that a future model cannot bypass.

At minimum verify:
- every cited evidence ID exists;
- a `confirmed` hypothesis has supporting evidence;
- a final recommendation cites evidence from the current session;
- invalid state transitions are rejected;
- an eliminated hypothesis cannot jump directly to confirmed without an explicitly valid transition/new support;
- insufficient evidence can result in `needs_input` instead of fabricated certainty.

Keep deterministic invariants authoritative. Do not add an LLM-based verifier in this milestone.

### Human handoff / resume semantics
- A session can enter `needs_input` with a concrete requested action/observation.
- Supplying the requested result can resume the same session without losing previous evidence/hypotheses.

## Initial test/example scenario

Use this only as a test fixture/example:

> Computer powers on and fans spin, but there is no display.

The engine should be able to represent several plausible causes and evidence updates without encoding a fixed troubleshooting script.

## Tests

Create deterministic local tests covering at minimum:
- session creation;
- valid state/status transitions;
- evidence insertion and provenance;
- multiple hypotheses coexisting;
- strengthening/supporting one hypothesis;
- weakening/eliminating another;
- invalid evidence references rejected;
- confirmation without supporting evidence rejected;
- final recommendation with missing/invalid evidence rejected;
- valid evidence-backed confirmation/recommendation accepted;
- `needs_input` → new evidence → resume flow;
- invalid eliminated → confirmed jump rejected;
- bounded completion-attempt behavior;
- serialization/round-trip if persistence is introduced.

Tests must require no network access.

## Constraints

- Create a feature branch; do not work directly on `main`.
- Do not create, modify, enable, or trigger GitHub Actions workflows.
- Do not add provider API calls yet.
- Do not build the frontend yet.
- Do not implement SAM, voice, deployment, partner inference, or provider failover yet.
- Do not import code/assets from previous Leonitex projects.
- Never commit secrets or `.env` files.
- Keep dependencies minimal; use the standard library where reasonable.
- Keep the implementation small and easy to inspect.
- Do not encode the primary demo as a fixed decision tree.
- Repository docs/code/tests are the source of truth.

## Working style

Before editing:
1. Read `HACKATHON_SCOPE.md`, `docs/architecture.md`, `docs/implementation-plan.md`, and `docs/codex-guidelines.md`.
2. Inspect the current repository rather than assuming a framework exists.
3. Briefly state the proposed file/module layout and why it is the smallest reasonable design.

Then implement Milestone 1 only.

## Completion report

Run the local tests and report:
- branch name;
- commit SHA;
- files added/changed;
- architecture decisions;
- exact commands run;
- exact test results;
- failures/warnings;
- known limitations;
- recommended next step.

Do not merge to `main`.