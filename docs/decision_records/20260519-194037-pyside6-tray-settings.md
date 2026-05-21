# PySide6 Windows Tray And Settings

## Context

The Windows tray menu only needs to expose status, settings, and exit. The previous Tk settings UI had focus and folder-dialog issues inside the packaged tray app.

## Decision

Move the Windows tray and settings window to PySide6 using `QSystemTrayIcon`, `QMenu`, and `QFileDialog.getExistingDirectory`. Keep the existing settings domain functions for saving configuration, validation, and Git remote handling.

## Consequences

- The Windows right-click menu is limited to `Status`, `Settings`, and `Exit`.
- The settings screen uses one Qt event loop instead of mixing tray callbacks with Tk dialogs.
- PySide6 becomes a Windows runtime dependency and is included in Windows builds.

