from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from willy.errors import WillyError


class LockError(WillyError):
    pass


@dataclass(frozen=True)
class LockInfo:
    name: str
    pid: int
    created_at: str
    purpose: str


@dataclass
class LockHandle:
    path: Path
    info: LockInfo
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self.released = True

    def __enter__(self) -> LockHandle:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            process_query_limited_information = 0x1000
            still_active = 259
            kernel32.OpenProcess.restype = ctypes.c_void_p
            handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            try:
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, SystemError):
        return False
    return True


def read_lock(path: Path) -> LockInfo | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    try:
        return LockInfo(
            name=str(data["name"]),
            pid=int(data["pid"]),
            created_at=str(data["created_at"]),
            purpose=str(data["purpose"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def acquire_lock(locks_dir: Path, name: str, *, purpose: str) -> LockHandle:
    locks_dir.mkdir(parents=True, exist_ok=True)
    path = locks_dir / f"{name}.lock"
    existing = read_lock(path)
    if existing and _pid_is_running(existing.pid):
        raise LockError(f"Another Willy process owns {name}: pid {existing.pid}, purpose {existing.purpose}")
    if existing:
        path.unlink(missing_ok=True)

    info = LockInfo(
        name=name,
        pid=os.getpid(),
        created_at=datetime.now().isoformat(timespec="seconds"),
        purpose=purpose,
    )
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise LockError(f"Could not acquire {name}; lock already exists: {path}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(info.__dict__, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return LockHandle(path=path, info=info)
