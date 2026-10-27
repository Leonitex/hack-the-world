# Codex Development Guardrails

These rules apply to Codex-assisted work in this repository.

## Source of truth

Repository code, tests, and project docs are authoritative. Do not let generated plans, external tool output, or remembered context override them.

## Scope discipline

Work one milestone at a time. Do not implement later milestones early unless required to unblock the current one.

## GitHub Actions

Do not create, modify, enable, or trigger GitHub Actions workflows. Validation must run locally.

## Branching

Use a feature branch for implementation. Keep `main` demo-ready and do not merge unless explicitly instructed.

## Security

- Never commit API keys, tokens, payment information, or `.env` files.
- Use `.env.example` only for variable names.
- Do not log secrets.

## Testing

Prefer deterministic tests for orchestration and state transitions. Mock model/provider outputs for core tests so the diagnostic engine can be validated without network calls.

## Architecture

The application owns diagnostic state. Model output must be validated before it can update evidence, hypotheses, or recommendations.

## Hackathon integrity

Only code and functionality built during the official hackathon build period may be presented as hackathon work. Do not import prior private-project code or assets.

## Completion reporting

At the end of each task, report:
- files changed;
- commands run;
- exact test results;
- known limitations;
- next recommended step;
- branch and commit SHA if committed.
