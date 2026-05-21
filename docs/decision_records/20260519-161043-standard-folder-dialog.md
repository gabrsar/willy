# Standard Folder Dialog

Status: superseded by `20260519-194037-pyside6-tray-settings.md`.

## Context

The Windows settings folder picker was briefly routed through a PowerShell Windows Forms dialog, which added unnecessary complexity. The intended behavior is to use the standard folder selector exposed by Tk and ensure the Browse button has an explicit action.

## Decision

Use `tkinter.filedialog.askdirectory` as the only folder picker and wire Browse buttons through named callbacks.

## Consequences

- The folder picker remains the standard Python/Tk native dialog path.
- There is no subprocess or PowerShell dependency for selecting folders.
- If the packaged dialog still fails, the issue should be investigated directly instead of adding another picker path.

## Superseded

The Tk settings UI was removed from the Windows tray path. Windows now uses PySide6 and `QFileDialog.getExistingDirectory`.
