from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

from willy.paths import WillyPaths


def default_orca_user_dir(paths: WillyPaths) -> Path:
    return paths.default_orca_user_dir


def _windows_orca_running(output: str) -> bool:
    normalized = output.lower()
    return "orcaslicer.exe" in normalized or "orca-slicer.exe" in normalized


def _windows_orca_running_native() -> bool:
    kernel32 = ctypes.windll.kernel32
    create_toolhelp_snapshot = kernel32.CreateToolhelp32Snapshot
    process_first = kernel32.Process32FirstW
    process_next = kernel32.Process32NextW
    close_handle = kernel32.CloseHandle
    create_toolhelp_snapshot.restype = ctypes.c_void_p
    th32cs_snapprocess = 0x00000002
    invalid_handle_value = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    snapshot = create_toolhelp_snapshot(th32cs_snapprocess, 0)
    if not snapshot or snapshot == invalid_handle_value:
        return False
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        if not process_first(snapshot, ctypes.byref(entry)):
            return False
        while True:
            name = entry.szExeFile.lower()
            if name in {"orcaslicer.exe", "orca-slicer.exe"}:
                return True
            if not process_next(snapshot, ctypes.byref(entry)):
                return False
    finally:
        close_handle(snapshot)


def is_orca_running() -> bool:
    if sys.platform == "win32":
        try:
            return _windows_orca_running_native()
        except Exception:
            return False
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
