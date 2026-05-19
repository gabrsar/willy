# Project Structure, AI Memory, And Dev Containers

## Context

Willy needs a predictable project structure for AI-assisted development, lightweight onboarding docs, and a development workflow that does not require contributors to install Python tooling directly on the host.

## Decision

- Keep project prompts in `docs/ai/`.
- Keep decision records in `docs/decision_records/`.
- Use `YYYYMMDD-HHMMSS-name.md` for both prompt and decision files.
- Add root-level `ai.md` with working rules for AI agents.
- Keep `README.md` short and focused on cloning, building, testing, and running.
- Add Dockerfiles under `deps/docker/` for Linux, Windows, and macOS-hosted development.
- Add a `justfile` as the main task runner.

## Notes

The macOS Dockerfile is for development from a macOS host, but it runs a Linux container. Docker does not provide native macOS containers, so macOS-only integrations still need host-level validation when changed.

## Consequences

- Future meaningful changes and PRs should include a decision record.
- Bug fixes should start with a failing regression test.
- Contributors can use `just` plus Docker for a clean dev environment.

