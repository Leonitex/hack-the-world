# Development Workflow

## Constraint

GitHub Actions/CI is intentionally not used for this hackathon repository because the available Actions quota is limited.

## Workflow

1. Develop on a feature branch.
2. Run tests and validation locally.
3. Use Codex for implementation assistance, refactoring, and test generation where useful.
4. Record meaningful validation commands and results in commit messages, pull-request notes, or `docs/validation-log.md`.
5. Keep `main` demo-ready; merge only validated changes.

## Validation priorities

- unit tests for evidence and hypothesis state transitions;
- schema validation for model responses;
- deterministic tests for orchestration logic using mocked model outputs;
- manual end-to-end demo runs for the primary troubleshooting scenario;
- lint/type checks locally where configured.

## Secrets

Never commit API keys, provider credentials, payment information, or `.env` files. Use `.env.example` for variable names only.
