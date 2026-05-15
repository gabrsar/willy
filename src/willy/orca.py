from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from willy.paths import WillyPaths


def default_orca_user_dir(paths: WillyPaths) -> Path:
    return paths.default_orca_user_dir


def _windows_orca_running(output: str) -> bool:
    normalized = output.lower()
    return "orcaslicer.exe" in normalized or "orca-slicer.exe" in normalized


def is_orca_running() -> bool:
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist"],
                text=True,
                capture_output=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        return _windows_orca_running(result.stdout)
    try:
        result = subprocess.run(
            ["pgrep", "-x", "OrcaSlicer"],
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
