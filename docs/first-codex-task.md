# First Codex Task — Milestone 1: Diagnostic Core

## Objective

Implement only the provider-independent diagnostic core described in `docs/architecture.md` and `docs/implementation-plan.md`.

## Required behavior

- Start a diagnostic session from a problem statement.
- Add evidence items with stable IDs and source metadata.
- Maintain multiple competing hypotheses.
- Support hypothesis states: `possible`, `supported`, `weakened`, `eliminated`, `confirmed`.
- Link supporting and contradicting evidence IDs to hypotheses.
- Represent the next diagnostic action separately from a final recommendation.
- Prevent a confirmed recommendation without supporting evidence.
- Keep all model/provider logic behind interfaces or placeholders; no live API integration in this milestone.

## Tests

Create deterministic local tests covering at minimum:
- session creation;
- evidence insertion;
- multiple hypotheses coexisting;
- evidence strengthening one hypothesis;
- evidence weakening/eliminating another hypothesis;
- invalid evidence references rejected;
- confirmation without supporting evidence rejected;
- serialization/round-trip of session state if persistence is introduced.

## Constraints

- Do not create or modify GitHub Actions workflows.
- Do not add provider API calls yet.
- Do not build the frontend yet.
- Do not import code/assets from previous projects.
- Never commit secrets or `.env` files.
- Keep the implementation small and easy to inspect.

## Completion report

Report files changed, architecture decisions, local commands run, exact test results, known limitations, branch name, and commit SHA. Do not merge to `main`.
