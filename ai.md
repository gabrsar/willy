# AI Agent Guidelines

These rules keep Willy changes small, testable, and easy to review.

## Project Memory

- Store AI prompts in `docs/ai/`.
- Store project decisions in `docs/decision_records/`.
- Name both kinds of files as `YYYYMMDD-HHMMSS-name.md`.
- Every meaningful code, docs, dependency, workflow, or PR change needs a matching decision record.

## Change Discipline

- Prefer small, focused changes that follow the existing project style.
- Read the relevant code and tests before editing.
- Do not rewrite unrelated files or revert user work.
- Keep public user-facing docs concise and operational.
- Use existing tooling before adding new dependencies.

## Tests

- Add or update tests for every behavior change.
- A bug fix must start with a failing test that reproduces the bug.
- Run the narrowest relevant test first, then the broader suite when the change is ready.
- If tests cannot run locally, document why and what remains unverified.

## Quality Gates

- Run formatting and linting before handing off.
- Keep `ruff` and `pytest` green for changed areas.
- Avoid hidden local requirements; prefer the Docker or `just` workflows documented in `README.md`.

## Pull Requests

- Every PR must reference its decision record.
- PR descriptions should include the reason for the change, test evidence, and user-visible impact.
- Do not merge code that changes behavior without tests or a documented exception.

## Security And Privacy

- Treat OrcaSlicer profile data as potentially sensitive.
- Do not commit printer IPs, API keys, tokens, passwords, or private profile data.
- Preserve Willy's conservative redaction behavior for public or unknown repositories.
- Prefer recovery-oriented errors over raw tracebacks in user-facing flows.

