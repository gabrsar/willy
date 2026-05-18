from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from willy.config import WillyConfig, WillyState, load_state, save_state
from willy.errors import WillyError
from willy.files import classify_path
from willy.locks import LockError, acquire_lock
from willy.logging import write_event
from willy.operations import save_profile_changes, sync_repo
from willy.paths import WillyPaths


class ChangeCollector(FileSystemEventHandler):
    def __init__(self, root: Path, *, asset_dirs: tuple[Path, ...] = ()) -> None:
        self.root = root
        self.asset_dirs = asset_dirs
        self.changed = False

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        paths = [Path(event.src_path)]
        dest_path = getattr(event, "dest_path", "")
        if dest_path:
            paths.append(Path(dest_path))
        if any(classify_path(self.root, path, asset_dirs=self.asset_dirs).trackable for path in paths):
            self.changed = True

    def consume(self) -> bool:
        changed = self.changed
        self.changed = False
        return changed


def pid_is_running(pid: int | None) -> bool:
    if not pid:
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


def _stop_pid(pid: int, *, force: bool) -> None:
    if sys.platform == "win32":
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return
    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


def start_background(paths: WillyPaths, state: WillyState) -> int:
    if pid_is_running(state.daemon_pid):
        return state.daemon_pid or 0
    paths.ensure_runtime_dirs()
    stdout = paths.logs_dir / "daemon.out.log"
    stderr = paths.logs_dir / "daemon.err.log"
    creationflags = 0
    executable = sys.executable
    args = [executable, "-m", "willy", "daemon"]
    if getattr(sys, "frozen", False):
        args = [executable, "--daemon"]
    if sys.platform == "win32":
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        if not getattr(sys, "frozen", False) and python.name.lower() == "python.exe" and pythonw.exists():
            executable = str(pythonw)
            args = [executable, "-m", "willy", "daemon"]
        creationflags = subprocess.CREATE_NO_WINDOW
    with stdout.open("a", encoding="utf-8") as out, stderr.open("a", encoding="utf-8") as err:
        process = subprocess.Popen(
            args,
            stdout=out,
            stderr=err,
            start_new_session=True,
            creationflags=creationflags,
        )
    save_state(paths, replace(state, daemon_pid=process.pid))
    return process.pid


def stop_background(paths: WillyPaths, state: WillyState, *, timeout_seconds: float = 5.0) -> bool:
    if not pid_is_running(state.daemon_pid):
        save_state(paths, replace(state, daemon_pid=None))
        return False
    assert state.daemon_pid is not None
    _stop_pid(state.daemon_pid, force=False)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not pid_is_running(state.daemon_pid):
            save_state(paths, replace(state, daemon_pid=None))
            return True
        time.sleep(0.1)
    _stop_pid(state.daemon_pid, force=True)
    save_state(paths, replace(state, daemon_pid=None))
    return True


def _flush(paths: WillyPaths, config: WillyConfig, *, description: str) -> None:
    state = load_state(paths)
    save_state(paths, replace(state, active_operation="saving"))
    try:
        result = save_profile_changes(
            config.repo_path,
            description=description,
            allow_sensitive=bool(config.repo_private),
            asset_dirs=config.asset_dirs,
        )
        if result.saved:
            write_event(paths, "daemon_commit", count=result.count, subject=result.subject)
    finally:
        save_state(paths, replace(load_state(paths), active_operation=None))


def _clear_pending(state: WillyState) -> WillyState:
    return replace(state, pending_save_since=None, next_save_at=None, pending_save_count=0)


def _mark_pending(state: WillyState, *, debounce_seconds: int) -> WillyState:
    now = datetime.now().astimezone()
    next_save = now + timedelta(seconds=debounce_seconds)
    return replace(
        state,
        pending_save_since=state.pending_save_since or now.isoformat(timespec="seconds"),
        next_save_at=next_save.isoformat(timespec="seconds"),
        pending_save_count=state.pending_save_count + 1,
    )


def run_daemon(
    paths: WillyPaths,
    config: WillyConfig,
    *,
    state: WillyState,
    is_orca_running_func,
    poll_seconds: float = 2.0,
    once: bool = False,
    stop_event=None,
) -> None:
    if not config.repo_path.exists():
        raise WillyError(f"Sync repo path does not exist: {config.repo_path}")

    try:
        lock = acquire_lock(paths.locks_dir, "daemon", purpose="watch profiles")
    except LockError:
        raise

    with lock:
        current_state = replace(state, daemon_pid=os.getpid())
        save_state(paths, current_state)
        write_event(paths, "daemon_started", repo=str(config.repo_path))
        was_running = False
        observer: Observer | None = None
        collector: ChangeCollector | None = None
        last_change = 0.0

        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return
                running = bool(is_orca_running_func())
                now = time.monotonic()

                if running and not was_running:
                    collector = ChangeCollector(config.repo_path, asset_dirs=config.asset_dirs)
                    observer = Observer()
                    observer.schedule(collector, str(config.repo_path), recursive=True)
                    observer.start()
                    write_event(paths, "orca_started", repo=str(config.repo_path))

                if running and collector and collector.consume():
                    last_change = now
                    current_state = _mark_pending(current_state, debounce_seconds=config.debounce_seconds)
                    save_state(paths, current_state)
                    write_event(paths, "watcher_batch_seen", repo=str(config.repo_path))

                if running and last_change and now - last_change >= config.debounce_seconds:
                    _flush(paths, config, description="Automatic save while OrcaSlicer is running")
                    current_state = _clear_pending(current_state)
                    save_state(paths, current_state)
                    last_change = 0.0

                if not running and was_running:
                    if observer:
                        observer.stop()
                        observer.join(timeout=5)
                    observer = None
                    collector = None
                    _flush(paths, config, description="Final save after OrcaSlicer closed")
                    sync_status = sync_repo(config.repo_path)
                    current_state = _clear_pending(
                        replace(
                            current_state,
                            last_sync_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                            last_sync_status=sync_status,
                            daemon_pid=os.getpid(),
                        )
                    )
                    save_state(paths, current_state)
                    write_event(paths, "orca_stopped", sync_status=sync_status)
                    if once:
                        return

                was_running = running
                if once and not running:
                    return
                if stop_event is not None:
                    stop_event.wait(poll_seconds)
                else:
                    time.sleep(poll_seconds)
        finally:
            if observer:
                observer.stop()
                observer.join(timeout=5)
            save_state(paths, _clear_pending(replace(current_state, daemon_pid=None)))
            write_event(paths, "daemon_stopped", repo=str(config.repo_path))
