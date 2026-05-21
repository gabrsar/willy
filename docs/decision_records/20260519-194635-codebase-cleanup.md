# Codebase Cleanup After PySide6 Migration

## Context

The Windows tray moved to PySide6, but the previous pystray/Tk implementation and Tk settings window remained in the codebase as dead code.

## Decision

Remove the dead Windows pystray/Tk path from `statusbar.py`, remove the obsolete Tk settings window from `tray_settings.py`, and keep settings persistence/validation as domain logic in `tray_settings.py`.

## Consequences

- `statusbar.py` is focused on shared status, daemon lifecycle, macOS status bar, and Windows delegation.
- `qt_tray.py` owns the Windows tray and settings UI.
- `tray_settings.py` owns settings validation and persistence logic.
- Tests import settings-domain helpers directly from `tray_settings.py`.

