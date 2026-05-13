from __future__ import annotations

import subprocess
from pathlib import Path

from willy.paths import WillyPaths


def default_orca_user_dir(paths: WillyPaths) -> Path:
    return paths.default_orca_user_dir


def is_orca_running() -> bool:
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
