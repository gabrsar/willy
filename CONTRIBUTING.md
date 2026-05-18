# Contributing

Thanks for helping make Willy safer and nicer for OrcaSlicer users.

## Development Setup

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 setup
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 lint
```

macOS/Linux:

```bash
make setup
make test
make lint
```

## Pull Request Checklist

- Keep user profile data private in tests and docs.
- Add or update tests for behavior changes.
- Run lint and tests before opening a PR.
- Keep generated build output out of Git.
- Bump the package version for user-visible behavior changes.

## Project Principles

- Local-first: Git is the source of truth, not a hosted service.
- Safe by default: unknown/public repositories redact sensitive printer fields.
- Boring recovery: every meaningful change should be inspectable with standard Git.
- Cross-platform: CLI behavior should work everywhere; tray features can be platform-specific.
