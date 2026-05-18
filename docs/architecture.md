# Architecture

Willy is intentionally small and local-first. The core flow is:

```text
OrcaSlicer profile directory
  -> file classification
  -> metadata/redaction
  -> Git commit
  -> Git sync
  -> tray/status feedback
```

## Modules

- `cli.py`: Typer command-line interface and setup workflow.
- `config.py`: persisted config/state model.
- `daemon.py`: file watcher and automatic save loop.
- `files.py`: trackable path classification for Orca profiles and project assets.
- `git.py`: Git subprocess wrapper and sync helpers.
- `operations.py`: save/sync orchestration.
- `redact.py`: sensitive field redaction.
- `statusbar.py`: macOS/Windows tray orchestration.
- `tray_settings.py`: Windows settings UI and config-save workflow.
- `tray_app.py`: frozen Windows GUI entrypoint with stdout/stderr log redirection.
- `windows_startup.py` and `launchd.py`: platform startup integration.

## Design Notes

- Keep Git behavior in `git.py`; do not shell out directly from UI code.
- Keep config writes in typed helpers so tests can cover them without opening windows.
- Keep Windows tray as a single process: duplicate launches signal the existing tray to open settings.
- Avoid committing generated artifacts such as `build/`, `dist/`, and PyInstaller specs.
