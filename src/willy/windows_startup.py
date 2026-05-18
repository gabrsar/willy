from __future__ import annotations

import os
import sys
from pathlib import Path

from willy.paths import WillyPaths

STARTUP_SCRIPT_NAME = "Willy Tray.vbs"


def startup_dir(paths: WillyPaths) -> Path:
    appdata = Path(os.environ.get("APPDATA", paths.home / "AppData" / "Roaming"))
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_script_path(paths: WillyPaths) -> Path:
    return startup_dir(paths) / STARTUP_SCRIPT_NAME


def windows_startup_enabled(paths: WillyPaths) -> bool:
    return startup_script_path(paths).exists()


def _pythonw_executable(executable: str | None = None) -> str:
    current = Path(executable or sys.executable)
    if current.name.lower() == "python.exe":
        pythonw = current.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(current)


def _python_executable(executable: str | None = None) -> str:
    current = Path(executable or sys.executable)
    if current.name.lower() == "pythonw.exe":
        python = current.with_name("python.exe")
        if python.exists():
            return str(python)
    return str(current)


def enable_windows_startup(paths: WillyPaths, *, executable: str | None = None) -> Path:
    script_path = startup_script_path(paths)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = Path(executable or sys.executable)
    if resolved.suffix.lower() == ".exe" and resolved.name.lower() not in {"python.exe", "pythonw.exe"}:
        tray_command = f'"{resolved}"'
    else:
        tray_command = f'"{_pythonw_executable(executable)}" -m willy statusbar'
    script_path.write_text(
        f'Set shell = CreateObject("WScript.Shell")\nshell.Run {tray_command!r}, 0, False\n',
        encoding="utf-8",
    )
    return script_path


def disable_windows_startup(paths: WillyPaths) -> Path:
    script_path = startup_script_path(paths)
    script_path.unlink(missing_ok=True)
    return script_path
