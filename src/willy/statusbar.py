from __future__ import annotations

import sys
import threading
import traceback
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from willy.config import WillyConfig, load_config, load_state, save_config, save_state
from willy.daemon import pid_is_running, run_daemon
from willy.errors import GitConflictError
from willy.git import (
    current_branch,
    is_repo,
    last_commit,
    remote_url,
    status_porcelain,
    sync_delta,
)
from willy.launchd import disable_launchd, enable_launchd, launchd_enabled
from willy.logging import setup_logging, write_event
from willy.operations import fetch_remote_updates, save_profile_changes, sync_repo, unsaved_summary
from willy.orca import is_orca_running
from willy.paths import WillyPaths, default_paths
from willy.windows_startup import disable_windows_startup, enable_windows_startup, windows_startup_enabled


@dataclass(frozen=True)
class StatusSnapshot:
    visible: bool
    phase: str
    icon_title: str
    summary: str
    details: str


_embedded_daemon_thread: threading.Thread | None = None
_embedded_daemon_stop_event: threading.Event | None = None
_windows_tray_mutex: Any | None = None
_OPEN_CONFIG_REQUEST = "tray-open-config.request"


def _asset_path(*parts: str) -> Path:
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir:
            candidates.append(Path(bundle_dir))
    candidates.extend([Path.cwd(), Path(__file__).resolve().parents[2]])
    for base in candidates:
        candidate = base.joinpath(*parts)
        if candidate.exists():
            return candidate
    return Path.cwd().joinpath(*parts)


def _embedded_daemon_running() -> bool:
    return bool(_embedded_daemon_thread and _embedded_daemon_thread.is_alive())


def _daemon_can_start(config: WillyConfig) -> bool:
    return config.repo_path.exists() and is_repo(config.repo_path)


def _acquire_windows_tray_mutex() -> bool:
    global _windows_tray_mutex
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, False, "Local\\WillyTraySingleton")
        if not mutex:
            return True
        already_exists = kernel32.GetLastError() == 183
        if already_exists:
            kernel32.CloseHandle(mutex)
            return False
        _windows_tray_mutex = mutex
        return True
    except Exception:
        return True


def _tray_open_config_request_path(paths: WillyPaths) -> Path:
    return paths.locks_dir / _OPEN_CONFIG_REQUEST


def _request_existing_tray_open_config(paths: WillyPaths) -> None:
    paths.ensure_runtime_dirs()
    request_path = _tray_open_config_request_path(paths)
    request_path.write_text(datetime.now().astimezone().isoformat(timespec="microseconds"), encoding="utf-8")
    write_event(paths, "statusbar_open_config_requested", platform="win32")


def _tray_open_config_request_mtime(paths: WillyPaths) -> float | None:
    try:
        return _tray_open_config_request_path(paths).stat().st_mtime
    except OSError:
        return None


def _release_windows_tray_mutex() -> None:
    global _windows_tray_mutex
    if sys.platform != "win32" or _windows_tray_mutex is None:
        return
    try:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(_windows_tray_mutex)
    finally:
        _windows_tray_mutex = None


def _windows_message_box(title: str, message: str, *, warning: bool = False, yes_no: bool = False) -> bool:
    import ctypes

    style = 0
    if warning:
        style |= 0x30
    else:
        style |= 0x40
    if yes_no:
        style |= 0x04
        return ctypes.windll.user32.MessageBoxW(None, message, title, style) == 6
    ctypes.windll.user32.MessageBoxW(None, message, title, style)
    return True


def _copy_text_to_clipboard(text: str) -> None:
    if sys.platform == "darwin":
        import subprocess

        subprocess.run(["pbcopy"], input=text, text=True, check=True)
        return
    raise RuntimeError("Clipboard copy is currently available on macOS only.")


def _start_embedded_daemon(paths: WillyPaths) -> None:
    global _embedded_daemon_stop_event, _embedded_daemon_thread
    if _embedded_daemon_running():
        return
    setup_logging(paths)
    config = load_config(paths)
    if not _daemon_can_start(config):
        write_event(paths, "embedded_daemon_skipped", repo=str(config.repo_path), reason="repo not ready")
        return
    state = load_state(paths)
    stop_event = threading.Event()

    def target() -> None:
        try:
            run_daemon(
                paths,
                config,
                state=state,
                is_orca_running_func=is_orca_running,
                poll_seconds=2.0,
                stop_event=stop_event,
            )
        except Exception as exc:
            write_event(paths, "embedded_daemon_failed", error=str(exc), traceback=traceback.format_exc())

    thread = threading.Thread(target=target, name="willy-embedded-daemon", daemon=True)
    _embedded_daemon_stop_event = stop_event
    _embedded_daemon_thread = thread
    thread.start()
    write_event(paths, "embedded_daemon_started")


def _stop_embedded_daemon(paths: WillyPaths) -> None:
    global _embedded_daemon_stop_event, _embedded_daemon_thread
    if _embedded_daemon_stop_event is not None:
        _embedded_daemon_stop_event.set()
    if _embedded_daemon_thread is not None:
        _embedded_daemon_thread.join(timeout=5)
    _embedded_daemon_stop_event = None
    _embedded_daemon_thread = None
    write_event(paths, "embedded_daemon_stopped")


def _sync_line(state) -> str:
    if not state.last_sync_status:
        return "none"
    if not state.last_sync_at:
        return state.last_sync_status
    return f"{state.last_sync_status} at {state.last_sync_at}"


def _phase(state, *, unsaved_count: int, sync_pending: bool) -> str:
    if state.last_sync_status and state.last_sync_status.startswith("conflict:"):
        return "conflict"
    if state.active_operation == "saving":
        return "saving"
    if state.pending_save_count or state.next_save_at or unsaved_count or sync_pending:
        return "pending"
    return "no pending"


def snapshot(
    paths: WillyPaths | None = None,
    *,
    is_orca_running_func=is_orca_running,
) -> StatusSnapshot:
    paths = paths or default_paths()
    config = load_config(paths)
    state = load_state(paths)
    orca_running = bool(is_orca_running_func())
    repo_ready = config.repo_path.exists() and is_repo(config.repo_path)
    unsaved = unsaved_summary(config.repo_path, asset_dirs=config.asset_dirs) if repo_ready else None
    unsaved_count = unsaved.count if unsaved else 0
    delta = sync_delta(config.repo_path) if repo_ready else None
    sync_pending = bool(delta and delta.pending)
    daemon_running = _embedded_daemon_running() or pid_is_running(state.daemon_pid)
    phase = _phase(state, unsaved_count=unsaved_count, sync_pending=sync_pending)
    title = {"no pending": "W", "pending": "W*", "saving": "W...", "conflict": "W!"}[phase]
    pending_count = unsaved_count or state.pending_save_count
    summary = {
        "no pending": "Willy: no pending changes",
        "pending": f"Willy: {pending_count} pending change(s)" if pending_count else "Willy: sync pending",
        "saving": "Willy: saving",
        "conflict": "Willy: conflict needs your decision",
    }[phase]
    branch = current_branch(config.repo_path) if repo_ready else None
    remote = remote_url(config.repo_path) if repo_ready else None
    last = last_commit(config.repo_path) if repo_ready else None
    changes = status_porcelain(config.repo_path) if repo_ready else []
    asset_lines = [f"Tracked asset dir: {path}" for path in config.asset_dirs] or ["Tracked asset dir: none"]
    details = "\n".join(
        [
            f"Status: {summary}",
            f"Orca running: {'yes' if orca_running else 'no'}",
            f"Daemon: {'running' if daemon_running else 'not running'}",
            f"Repo: {config.repo_path}",
            f"Branch: {branch or 'unknown'}",
            f"Remote: {remote or 'none'}",
            f"Uncommitted changes: {len(changes)}",
            f"Unsaved tracked files: {unsaved_count}",
            *asset_lines,
            "Sync pending: "
            + (
                f"yes ({delta.ahead} ahead, {delta.behind} behind)"
                if delta and not delta.needs_upstream
                else "yes (upstream not configured)"
                if delta and delta.needs_upstream
                else "no"
            ),
            f"Next save: {state.next_save_at or 'none'}",
            f"Last commit: {last or state.last_commit or 'none'}",
            f"Last sync: {_sync_line(state)}",
            "Sensitive fields: "
            + ("kept in commits; repo must not become public" if config.repo_private else "redacted before commit"),
        ]
    )
    visible = True if sys.platform == "win32" else orca_running or phase != "no pending"
    return StatusSnapshot(
        visible=visible,
        phase=phase,
        icon_title=title,
        summary=summary,
        details=details,
    )


def check_remote_on_load(paths: WillyPaths | None = None) -> str:
    paths = paths or default_paths()
    setup_logging(paths)
    config = load_config(paths)
    if not config.repo_path.exists() or not is_repo(config.repo_path):
        return "Sync repo is not ready. Run willy setup first."
    try:
        fetch_status = fetch_remote_updates(config.repo_path)
        delta = sync_delta(config.repo_path)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        if fetch_status == "no remote configured":
            message = fetch_status
        elif delta.pending:
            if delta.needs_upstream:
                message = "Remote check complete. Sync setup still needs an upstream branch."
            elif delta.behind:
                message = (
                    f"Remote updates are available ({delta.behind} commit(s) to download). Use Force Sync / Download."
                )
            elif delta.ahead:
                message = f"Local saves are waiting to upload ({delta.ahead} commit(s)). Use Force Sync / Download."
            else:
                message = fetch_status
        else:
            message = "Remote check complete. Willy is up to date."
        save_state(paths, replace(load_state(paths), last_sync_at=now, last_sync_status=message))
        write_event(paths, "statusbar_load_remote_check", status=message)
        return message
    except Exception as exc:
        message = f"Remote check failed: {exc}"
        save_state(paths, replace(load_state(paths), last_sync_status=message))
        write_event(paths, "statusbar_load_remote_check_failed", error=str(exc), traceback=traceback.format_exc())
        return message


def force_sync(paths: WillyPaths | None = None) -> str:
    paths = paths or default_paths()
    setup_logging(paths)
    config = load_config(paths)
    if not config.repo_path.exists() or not is_repo(config.repo_path):
        return "Sync repo is not ready. Run willy setup first."

    save_state(paths, replace(load_state(paths), active_operation="saving"))
    try:
        result = save_profile_changes(
            config.repo_path,
            description="Manual tray sync",
            allow_sensitive=bool(config.repo_private),
            asset_dirs=config.asset_dirs,
        )
        try:
            sync_status = sync_repo(config.repo_path)
        except GitConflictError as exc:
            sync_status = f"conflict: {exc}"
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        state = load_state(paths)
        save_state(paths, replace(state, active_operation=None, last_sync_at=now, last_sync_status=sync_status))
        write_event(paths, "statusbar_force_sync", saved=result.saved, count=result.count, sync_status=sync_status)
        saved_text = f"Saved {result.count} file(s)." if result.saved else "Nothing to save."
        return f"{saved_text}\nSync: {sync_status}"
    except Exception:
        save_state(paths, replace(load_state(paths), active_operation=None))
        raise


def dismiss_tray_welcome(paths: WillyPaths) -> None:
    config = load_config(paths)
    save_config(paths, replace(config, show_tray_welcome=False))
    write_event(paths, "statusbar_welcome_dismissed")


def _startup_enabled(paths: WillyPaths, config: WillyConfig) -> bool:
    if sys.platform == "win32":
        return windows_startup_enabled(paths) or config.tray_enabled
    return launchd_enabled(paths) or config.launchd_enabled


def _set_startup_enabled(paths: WillyPaths, config: WillyConfig, enabled: bool) -> str:
    if sys.platform == "win32":
        if enabled:
            script_path = enable_windows_startup(paths)
            save_config(paths, replace(config, tray_enabled=True))
            return f"Willy tray and daemon will start on login.\n{script_path}"
        script_path = disable_windows_startup(paths)
        save_config(paths, replace(config, tray_enabled=False))
        return f"Willy tray startup disabled.\nStart them manually with: willy start and willy statusbar\n{script_path}"
    if enabled:
        plist_path = enable_launchd(paths)
        save_config(paths, replace(config, launchd_enabled=True))
        return f"Willy daemon will start on login.\n{plist_path}"
    plist_path = disable_launchd(paths)
    save_config(paths, replace(config, launchd_enabled=False))
    return f"Willy daemon startup disabled.\nStart it manually with: willy start\n{plist_path}"


def _run_macos_statusbar(*, poll_seconds: float, start_daemon: bool) -> None:
    try:
        import objc
        from AppKit import (
            NSAlert,
            NSAlertFirstButtonReturn,
            NSApplication,
            NSApplicationActivationPolicyAccessory,
            NSInformationalAlertStyle,
            NSMenu,
            NSMenuItem,
            NSStatusBar,
            NSVariableStatusItemLength,
            NSWarningAlertStyle,
        )
        from Foundation import NSObject, NSTimer
    except ImportError as exc:
        raise RuntimeError("The macOS status bar requires PyObjC. Reinstall Willy and try again.") from exc

    paths = default_paths()
    setup_logging(paths)
    if start_daemon:
        _start_embedded_daemon(paths)

    class StatusBarController(NSObject):
        def initWithPollSeconds_(self, seconds):
            self = objc.super(StatusBarController, self).init()
            if self is None:
                return None
            self.status_item = None
            self.last_snapshot = None
            self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                seconds,
                self,
                "refresh:",
                None,
                True,
            )
            return self

        def refresh_(self, _sender):
            current = snapshot(paths)
            self.last_snapshot = current
            if not current.visible:
                self.removeItem()
                return
            self.ensureItem()
            self.status_item.button().setTitle_(current.icon_title)
            self.rebuildMenu()

        def ensureItem(self):
            if self.status_item is not None:
                return
            self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)

        def removeItem(self):
            if self.status_item is not None:
                NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)
                self.status_item = None

        def rebuildMenu(self):
            menu = NSMenu.alloc().init()
            status_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                self.last_snapshot.summary if self.last_snapshot else "Willy",
                None,
                "",
            )
            status_item.setEnabled_(False)
            menu.addItem_(status_item)
            menu.addItem_(NSMenuItem.separatorItem())
            self.addMenuItem(menu, "Copy Status", "copyStatus:")
            self.addMenuItem(menu, "Detailed Status...", "showDetails:")
            self.addMenuItem(menu, "Force Sync / Download", "forceSync:")
            self.addMenuItem(menu, "Configure Files / Projects Folder...", "configureProjectFolder:")
            config = load_config(paths)
            enabled = _startup_enabled(paths, config)
            title = "Disable daemon on system start..." if enabled else "Enable daemon on system start"
            self.addMenuItem(menu, title, "toggleStartup:")
            menu.addItem_(NSMenuItem.separatorItem())
            self.addMenuItem(menu, "Quit Willy Status Bar", "quit:")
            self.status_item.setMenu_(menu)

        def addMenuItem(self, menu, title, action):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            item.setTarget_(self)
            menu.addItem_(item)

        def showDetails_(self, _sender):
            self.refresh_(None)
            self.showMessage_title_style_(self.last_snapshot.details, "Willy Status", NSInformationalAlertStyle)

        def copyStatus_(self, _sender):
            self.refresh_(None)
            try:
                _copy_text_to_clipboard(self.last_snapshot.details)
                message = "Status copied to clipboard."
            except Exception as exc:
                message = f"Could not copy status:\n{exc}"
            self.showMessage_title_style_(message, "Willy Status", NSInformationalAlertStyle)

        def forceSync_(self, _sender):
            try:
                message = force_sync(paths)
            except Exception as exc:
                message = f"Force sync failed:\n{exc}"
            self.refresh_(None)
            self.showMessage_title_style_(message, "Willy Sync", NSInformationalAlertStyle)

        def configureProjectFolder_(self, _sender):
            self.showMessage_title_style_(
                "Configure this from the Windows tray for now.",
                "Willy Files / Projects",
                NSInformationalAlertStyle,
            )

        def toggleStartup_(self, _sender):
            config = load_config(paths)
            enabled = _startup_enabled(paths, config)
            if enabled and not self.confirmDisableStartup():
                return
            try:
                message = _set_startup_enabled(paths, config, not enabled)
            except Exception as exc:
                message = f"Could not update daemon startup:\n{exc}"
            self.refresh_(None)
            self.showMessage_title_style_(message, "Willy Startup", NSInformationalAlertStyle)

        def confirmDisableStartup(self):
            alert = NSAlert.alloc().init()
            alert.setAlertStyle_(NSWarningAlertStyle)
            alert.setMessageText_("Disable Willy daemon on system start?")
            alert.setInformativeText_(
                "If you disable this, Willy will not start automatically after login. "
                "You will need to run `willy start` manually."
            )
            alert.addButtonWithTitle_("Disable")
            alert.addButtonWithTitle_("Cancel")
            return alert.runModal() == NSAlertFirstButtonReturn

        def showMessage_title_style_(self, message, title, style):
            alert = NSAlert.alloc().init()
            alert.setAlertStyle_(style)
            alert.setMessageText_(title)
            alert.setInformativeText_(message)
            alert.runModal()

        def quit_(self, _sender):
            _stop_embedded_daemon(paths)
            NSApplication.sharedApplication().terminate_(self)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = StatusBarController.alloc().initWithPollSeconds_(poll_seconds)
    controller.refresh_(None)
    load_message = check_remote_on_load(paths)
    controller.refresh_(None)
    if "available" in load_message or "failed" in load_message or "upstream" in load_message:
        controller.showMessage_title_style_(load_message, "Willy", NSInformationalAlertStyle)
    write_event(paths, "statusbar_started", platform="darwin")
    try:
        app.run()
    finally:
        _stop_embedded_daemon(paths)


def _run_windows_tray(*, poll_seconds: float, start_daemon: bool) -> None:
    from willy.qt_tray import run_windows_tray as run_qt_windows_tray

    run_qt_windows_tray(poll_seconds=poll_seconds, start_daemon=start_daemon)


def run_statusbar(*, poll_seconds: float = 2.0, start_daemon: bool = True) -> None:
    if sys.platform == "darwin":
        _run_macos_statusbar(poll_seconds=poll_seconds, start_daemon=start_daemon)
        return
    if sys.platform == "win32":
        _run_windows_tray(poll_seconds=poll_seconds, start_daemon=start_daemon)
        return
    raise RuntimeError("Tray/status bar support is currently available on macOS and Windows only.")


def main(*, start_daemon: bool = True) -> int:
    try:
        run_statusbar(start_daemon=start_daemon)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0
