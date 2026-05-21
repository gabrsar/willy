# Canonical Just Build Target

## Context

The project had a Windows-specific `build-windows-exe` recipe, but no canonical `build` recipe. That made it too easy to bypass the task runner and call scripts directly.

## Decision

Add `just build` as the primary build recipe for the Windows tray executable and keep `build-windows-exe` as an alias.

## Consequences

- Contributors have one obvious build command.
- The existing explicit Windows recipe still works.
- Build automation should call `just build` instead of invoking `scripts/dev.ps1 build-exe` directly.

