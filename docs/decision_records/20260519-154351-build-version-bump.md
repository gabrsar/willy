# Build Version Bump

## Context

The tray settings window displays Willy's package version. After settings UI changes, the source and package metadata still reported `0.1.7`, making it hard to tell whether a rebuilt executable contained the latest code.

## Decision

Bump Willy from `0.1.7` to `0.1.8` before rebuilding the Windows tray executable.

## Consequences

- The settings window can confirm the new build by showing `v0.1.8`.
- Version metadata remains synchronized between `pyproject.toml` and `src/willy/__init__.py`.

