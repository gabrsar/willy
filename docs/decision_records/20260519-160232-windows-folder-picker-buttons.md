# Windows Folder Picker Button Behavior

Status: superseded by `20260519-194037-pyside6-tray-settings.md`.

## Context

Inside the Windows tray executable, the Tk folder picker could show native `Select Folder` and `Cancel` buttons that did not complete the interaction reliably.

## Decision

Use a Windows Forms `FolderBrowserDialog` launched through PowerShell STA for Windows folder selection, while keeping the Tk filedialog fallback for other platforms. Also make the settings `Cancel` action explicitly quit and destroy the Tk window.

## Consequences

- Folder selection and cancellation use a Windows-native dialog path in the packaged tray app.
- The settings window's cancel button closes the Tk event loop more reliably.
- Directory paths can still be edited manually and are still validated on save.

## Superseded

This PowerShell/Windows Forms path was removed. Windows now uses the PySide6 settings UI and `QFileDialog.getExistingDirectory`.
