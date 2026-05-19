from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from willy.paths import WillyPaths

LABEL = "com.willy.daemon"


def launch_agent_dir(paths: WillyPaths) -> Path:
    return paths.home / "Library" / "LaunchAgents"


def launch_agent_path(paths: WillyPaths) -> Path:
    return launch_agent_dir(paths) / f"{LABEL}.plist"


def launchd_plist(paths: WillyPaths, *, executable: str | None = None) -> dict:
    executable = executable or sys.executable
    return {
        "Label": LABEL,
        "ProgramArguments": [executable, "-m", "willy", "daemon"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(paths.logs_dir / "launchd.out.log"),
        "StandardErrorPath": str(paths.logs_dir / "launchd.err.log"),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"),
        },
    }


def launchd_enabled(paths: WillyPaths) -> bool:
    return launch_agent_path(paths).exists()


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(("launchctl", *args), text=True, capture_output=True, check=False, timeout=20)


def enable_launchd(paths: WillyPaths, *, executable: str | None = None) -> Path:
    paths.ensure_runtime_dirs()
    launch_agent_dir(paths).mkdir(parents=True, exist_ok=True)
    plist_path = launch_agent_path(paths)
    with plist_path.open("wb") as handle:
        plistlib.dump(launchd_plist(paths, executable=executable), handle)
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(plist_path))
    _launchctl("bootstrap", domain, str(plist_path))
    _launchctl("enable", f"{domain}/{LABEL}")
    return plist_path


def disable_launchd(paths: WillyPaths) -> Path:
    plist_path = launch_agent_path(paths)
    domain = f"gui/{os.getuid()}"
    if plist_path.exists():
        _launchctl("bootout", domain, str(plist_path))
        plist_path.unlink()
    return plist_path
