from __future__ import annotations

import sys
import threading
import traceback
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from willy import __version__
from willy.config import WillyConfig, load_config, load_state, save_config, save_state
from willy.daemon import pid_is_running, run_daemon
from willy.git import (
    current_branch,
    is_repo,
    last_commit,
    remote_refs,
    remote_url,
    status_porcelain,
    sync_delta,
    validate_remote_access,
)
from willy.launchd import disable_launchd, enable_launchd, launchd_enabled
from willy.logging import setup_logging, write_event
from willy.operations import save_profile_changes, sync_repo, unsaved_summary
from willy.orca import is_orca_running
from willy.paths import WillyPaths, default_paths
from willy.tray_settings import (
    clear_project_folder,
    configure_project_folder,
    configure_repository,
    suggested_project_folder,
)
from willy.tray_settings import (
    show_settings_window as open_settings_window,
)
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
    title = {"no pending": "W", "pending": "W*", "saving": "W..."}[phase]
    pending_count = unsaved_count or state.pending_save_count
    summary = {
        "no pending": "Willy: no pending changes",
        "pending": f"Willy: {pending_count} pending change(s)" if pending_count else "Willy: sync pending",
        "saving": "Willy: saving",
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
        sync_status = sync_repo(config.repo_path)
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
    write_event(paths, "statusbar_started", platform="darwin")
    try:
        app.run()
    finally:
        _stop_embedded_daemon(paths)


def _run_windows_tray(*, poll_seconds: float, start_daemon: bool) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("The Windows tray icon requires pystray and pillow. Reinstall Willy and try again.") from exc

    paths = default_paths()
    setup_logging(paths)
    if not _acquire_windows_tray_mutex():
        _request_existing_tray_open_config(paths)
        write_event(paths, "statusbar_duplicate_instance", platform="win32")
        return
    if start_daemon:
        _start_embedded_daemon(paths)
    state = {"snapshot": snapshot(paths)}
    refresh_index = 0
    stop_event = threading.Event()
    config_window_lock = threading.Lock()
    last_open_config_request = {"mtime": _tray_open_config_request_mtime(paths)}

    def tray_image(phase: str):
        icon_path = _asset_path("assets", "icon.png")
        if icon_path.exists():
            return Image.open(icon_path).convert("RGBA").resize((64, 64))
        background = {"no pending": "#1f7a4c", "pending": "#c97a11", "saving": "#295fa6"}[phase]
        fallback = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(fallback)
        draw.rounded_rectangle((6, 6, 58, 58), radius=12, fill=background)
        draw.text((20, 15), "W", fill="white")
        return fallback

    def show_message(title: str, message: str, *, warning: bool = False) -> None:
        _windows_message_box(title, message, warning=warning)

    def show_status_window(title: str, message: str) -> None:
        from tkinter import BOTH, LEFT, RIGHT, VERTICAL, Button, Frame, Label, Scrollbar, Text, Tk

        window = Tk()
        window.title(title)
        window.geometry("720x420")
        window.minsize(520, 320)

        frame = Frame(window, padx=12, pady=12)
        frame.pack(fill=BOTH, expand=True)

        text = Text(frame, wrap="word", height=16, width=80)
        scrollbar = Scrollbar(frame, orient=VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.insert("1.0", message)
        text.configure(state="disabled")
        text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill="y")

        footer = Frame(window, padx=12, pady=(0, 12))
        footer.pack(fill="x")
        status = Label(footer, text="")
        status.pack(side=LEFT)

        def copy_to_clipboard() -> None:
            window.clipboard_clear()
            window.clipboard_append(message)
            window.update()
            status.configure(text="Status copied.")
            write_event(
                paths,
                "statusbar_action",
                action="copy_status",
                phase=state["snapshot"].phase,
                platform="win32",
            )

        Button(footer, text="Copy Status", command=copy_to_clipboard).pack(side=RIGHT, padx=(8, 0))
        Button(footer, text="Close", command=window.destroy).pack(side=RIGHT)
        window.lift()
        window.focus_force()
        window.mainloop()

    def show_welcome_window() -> None:
        from tkinter import BooleanVar, Button, Checkbutton, Label, Tk

        config = load_config(paths)
        if not config.show_tray_welcome:
            return

        window = Tk()
        window.title("Willy")
        window.geometry("360x160")
        window.resizable(False, False)

        Label(
            window,
            text="Willy is running in the Windows tray.\nLook for the icon near the clock.",
            padx=16,
            pady=16,
            justify="left",
        ).pack(fill="x")

        dont_show_again = BooleanVar(value=True)
        Checkbutton(window, text="Do not show again", variable=dont_show_again).pack(anchor="w", padx=16)

        def close() -> None:
            if dont_show_again.get():
                dismiss_tray_welcome(paths)
            else:
                write_event(paths, "statusbar_welcome_kept")
            window.destroy()

        Button(window, text="OK", command=close).pack(pady=12)
        window.protocol("WM_DELETE_WINDOW", close)
        window.lift()
        window.focus_force()
        write_event(paths, "statusbar_welcome_shown")
        window.mainloop()

    def refresh_once() -> None:
        nonlocal refresh_index
        refresh_index += 1
        write_event(paths, "statusbar_refresh_begin", index=refresh_index, platform="win32")
        current = snapshot(paths)
        state["snapshot"] = current
        icon.icon = tray_image(current.phase)
        icon.title = current.summary
        icon.update_menu()
        write_event(
            paths,
            "statusbar_refresh_complete",
            index=refresh_index,
            phase=current.phase,
            summary=current.summary,
            platform="win32",
        )

    def refresh_loop() -> None:
        while not stop_event.wait(poll_seconds):
            try:
                refresh_once()
            except Exception:
                write_event(paths, "statusbar_refresh_failed", traceback=traceback.format_exc(), platform="win32")

    def open_repository_window_once(source: str) -> None:
        if not config_window_lock.acquire(blocking=False):
            write_event(paths, "statusbar_repository_config_already_open", source=source, platform="win32")
            return
        try:
            write_event(paths, "statusbar_action", action="configure_repository_open", source=source, platform="win32")
            open_settings_window(
                paths,
                refresh_once=refresh_once,
                startup_enabled=_startup_enabled,
                set_startup_enabled=_set_startup_enabled,
            )
        finally:
            config_window_lock.release()

    def open_config_request_loop() -> None:
        while not stop_event.wait(0.5):
            try:
                current_mtime = _tray_open_config_request_mtime(paths)
                if current_mtime is None or current_mtime == last_open_config_request["mtime"]:
                    continue
                last_open_config_request["mtime"] = current_mtime
                open_repository_window_once("duplicate_launch")
            except Exception:
                write_event(
                    paths,
                    "statusbar_open_config_request_failed",
                    traceback=traceback.format_exc(),
                    platform="win32",
                )

    def show_details(icon_obj, item) -> None:
        write_event(
            paths,
            "statusbar_action",
            action="details",
            phase=state["snapshot"].phase,
            platform="win32",
        )
        show_status_window("Willy Status", state["snapshot"].details)

    def do_force_sync(icon_obj, item) -> None:
        try:
            write_event(
                paths,
                "statusbar_action",
                action="force_sync",
                phase=state["snapshot"].phase,
                platform="win32",
            )
            message = force_sync(paths)
        except Exception as exc:
            message = f"Force sync failed:\n{exc}"
        refresh_once()
        show_message("Willy Sync", message)

    def show_project_folder_window() -> None:
        from tkinter import BOTH, LEFT, RIGHT, StringVar, Tk, filedialog, messagebox, ttk

        config = load_config(paths)
        current = config.asset_dirs[0] if config.asset_dirs else suggested_project_folder(config)

        window = Tk()
        window.title("Willy Files / Projects")
        window.geometry("760x300")
        window.minsize(620, 280)
        window.configure(bg="#f3f4f6")
        window.attributes("-topmost", True)
        window.after(700, lambda: window.attributes("-topmost", False))

        style = ttk.Style(window)
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("Title.TLabel", background="#ffffff", font=("Segoe UI", 14, "bold"))
        style.configure("Body.TLabel", background="#ffffff", font=("Segoe UI", 9))
        style.configure("Hint.TLabel", background="#ffffff", foreground="#4b5563", font=("Segoe UI", 9))
        style.configure("Status.TLabel", background="#ffffff", foreground="#1f2937", font=("Segoe UI", 9))
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))

        container = ttk.Frame(window, style="Card.TFrame", padding=20)
        container.pack(fill=BOTH, expand=True)

        ttk.Label(container, text="Files & Projects Folder", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            container,
            text="Choose the folder Willy should watch for .3mf and .stl files.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(4, 16))

        ttk.Label(container, text="Sync repo", style="Body.TLabel").pack(anchor="w")
        ttk.Label(container, text=str(config.repo_path), style="Hint.TLabel", wraplength=700, justify=LEFT).pack(
            anchor="w", pady=(2, 12)
        )
        ttk.Label(container, text="Tracked folder", style="Body.TLabel").pack(anchor="w")

        folder_var = StringVar(value=str(current))
        entry_row = ttk.Frame(container, style="Card.TFrame")
        entry_row.pack(fill="x", pady=(2, 10))
        entry = ttk.Entry(entry_row, textvariable=folder_var)
        entry.pack(side=LEFT, fill="x", expand=True)

        status = ttk.Label(
            container,
            text="Pick a folder inside the sync repo, or clear it to stop tracking project files.",
            style="Status.TLabel",
            wraplength=700,
            justify=LEFT,
        )
        status.pack(anchor="w", pady=(0, 12))

        buttons = ttk.Frame(container, style="Card.TFrame")
        buttons.pack(fill="x")

        def use_suggested() -> None:
            folder_var.set(str(suggested_project_folder(load_config(paths))))
            status.configure(text="Suggested folder selected. Click Save to apply it.")

        def browse() -> None:
            latest_config = load_config(paths)
            initial_dir = Path(folder_var.get().strip().strip('"') or latest_config.repo_path).expanduser()
            if not initial_dir.exists():
                initial_dir = latest_config.repo_path
            selected = filedialog.askdirectory(
                parent=window,
                title="Choose Willy files and projects folder",
                initialdir=str(initial_dir),
                mustexist=True,
            )
            if selected:
                folder_var.set(selected)
                status.configure(text="Folder selected. Click Save to apply it.")

        def clear() -> None:
            message = clear_project_folder(paths)
            folder_var.set("")
            status.configure(text=message)
            refresh_once()

        def save() -> None:
            selected = folder_var.get().strip().strip('"')
            if not selected:
                status.configure(text="Enter a folder path.")
                return
            folder = Path(selected).expanduser()
            create_missing = True
            if not folder.exists():
                write_event(
                    paths,
                    "statusbar_project_folder_missing",
                    folder=str(folder),
                    platform="win32",
                )
                create_missing = messagebox.askyesno(
                    "Willy Files / Projects",
                    f"This folder does not exist yet.\n\n{folder}\n\nDo you want Willy to create it?",
                    parent=window,
                )
                if not create_missing:
                    status.configure(text="Choose another folder, or click Save again if you change your mind.")
                    browse()
                    return
            write_event(paths, "statusbar_action", action="configure_project_folder", folder=selected, platform="win32")
            message = configure_project_folder(paths, selected, create_missing=create_missing)
            status.configure(text=message)
            refresh_once()
            if message.startswith("Files and projects folder configured:"):
                window.after(900, window.destroy)

        ttk.Button(entry_row, text="Browse...", command=browse).pack(side=RIGHT, padx=(8, 0))
        ttk.Button(buttons, text="Use Suggested", command=use_suggested).pack(side=LEFT)
        ttk.Button(buttons, text="Clear", command=clear).pack(side=LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side=RIGHT)
        ttk.Button(buttons, text="Save", command=save, style="Accent.TButton").pack(side=RIGHT, padx=(0, 8))

        entry.focus_set()
        window.lift()
        window.focus_force()
        window.mainloop()

    def show_repository_window() -> None:
        from tkinter import BOTH, LEFT, RIGHT, BooleanVar, StringVar, Tk, filedialog, messagebox, ttk

        config = load_config(paths)

        window = Tk()
        window.title("Willy Repository Settings")
        window.geometry("820x470")
        window.minsize(700, 430)
        window.configure(bg="#f3f4f6")
        window.attributes("-topmost", True)
        window.after(700, lambda: window.attributes("-topmost", False))

        style = ttk.Style(window)
        style.configure("RepoCard.TFrame", background="#ffffff", relief="flat")
        style.configure("RepoTitle.TLabel", background="#ffffff", font=("Segoe UI", 14, "bold"))
        style.configure("RepoBody.TLabel", background="#ffffff", font=("Segoe UI", 9))
        style.configure("RepoHint.TLabel", background="#ffffff", foreground="#4b5563", font=("Segoe UI", 9))
        style.configure("RepoStatus.TLabel", background="#ffffff", foreground="#1f2937", font=("Segoe UI", 9))
        style.configure("RepoAccent.TButton", font=("Segoe UI", 9, "bold"))

        container = ttk.Frame(window, style="RepoCard.TFrame", padding=20)
        container.pack(fill=BOTH, expand=True)

        ttk.Label(container, text="Repository Settings", style="RepoTitle.TLabel").pack(anchor="w")
        ttk.Label(
            container,
            text="Configure where Willy stores Orca profiles, Git sync, remote origin, and privacy behavior.",
            style="RepoHint.TLabel",
        ).pack(anchor="w", pady=(4, 16))

        orca_var = StringVar(value=str(config.orca_user_dir))
        repo_var = StringVar(value=str(config.repo_path))
        remote_var = StringVar(value=config.remote or remote_url(config.repo_path) or "")
        branch_var = StringVar(value=current_branch(config.repo_path) or config.branch or "main")
        privacy_var = StringVar(
            value=(
                "Private repo: keep sensitive fields"
                if config.repo_private
                else "Public/unknown: redact sensitive fields"
            )
        )
        init_var = BooleanVar(value=True)
        validate_var = BooleanVar(value=False)

        def folder_row(label: str, variable: StringVar) -> None:
            ttk.Label(container, text=label, style="RepoBody.TLabel").pack(anchor="w")
            row = ttk.Frame(container, style="RepoCard.TFrame")
            row.pack(fill="x", pady=(2, 10))
            ttk.Entry(row, textvariable=variable).pack(side=LEFT, fill="x", expand=True)

            def browse_folder() -> None:
                initial = Path(variable.get().strip().strip('"') or config.repo_path).expanduser()
                if not initial.exists():
                    initial = config.repo_path if config.repo_path.exists() else Path.home()
                selected = filedialog.askdirectory(
                    parent=window,
                    title=f"Choose {label.lower()}",
                    initialdir=str(initial),
                    mustexist=True,
                )
                if selected:
                    variable.set(selected)

            ttk.Button(row, text="Browse...", command=browse_folder).pack(side=RIGHT, padx=(8, 0))

        folder_row("Orca profile directory", orca_var)
        folder_row("Repository folder", repo_var)

        ttk.Label(container, text="Git remote origin", style="RepoBody.TLabel").pack(anchor="w")
        ttk.Entry(container, textvariable=remote_var).pack(fill="x", pady=(2, 10))

        branch_row = ttk.Frame(container, style="RepoCard.TFrame")
        branch_row.pack(fill="x", pady=(0, 10))
        left = ttk.Frame(branch_row, style="RepoCard.TFrame")
        left.pack(side=LEFT, fill="x", expand=True, padx=(0, 12))
        ttk.Label(left, text="Branch", style="RepoBody.TLabel").pack(anchor="w")
        ttk.Entry(left, textvariable=branch_var).pack(fill="x", pady=(2, 0))
        right = ttk.Frame(branch_row, style="RepoCard.TFrame")
        right.pack(side=RIGHT, fill="x", expand=True)
        ttk.Label(right, text="Privacy", style="RepoBody.TLabel").pack(anchor="w")
        ttk.Combobox(
            right,
            textvariable=privacy_var,
            state="readonly",
            values=("Public/unknown: redact sensitive fields", "Private repo: keep sensitive fields"),
        ).pack(fill="x", pady=(2, 0))

        ttk.Checkbutton(container, text="Initialize Git repo if needed", variable=init_var).pack(anchor="w")
        ttk.Checkbutton(container, text="Validate remote access before saving", variable=validate_var).pack(anchor="w")

        status = ttk.Label(
            container,
            text="Remote validation can take a few seconds, especially over SSH.",
            style="RepoStatus.TLabel",
            wraplength=760,
            justify=LEFT,
        )
        status.pack(anchor="w", pady=(12, 12))

        buttons = ttk.Frame(container, style="RepoCard.TFrame")
        buttons.pack(fill="x")

        def clear_remote() -> None:
            remote_var.set("")
            status.configure(text="Remote cleared. Click Save to apply it.")

        def save() -> None:
            orca_text = orca_var.get().strip().strip('"')
            repo_text = repo_var.get().strip().strip('"')
            if not orca_text or not repo_text:
                status.configure(text="Orca profile directory and repository folder are required.")
                return

            missing = [
                Path(value).expanduser()
                for value in (orca_text, repo_text)
                if value and not Path(value).expanduser().exists()
            ]
            create_missing = True
            if missing:
                missing_text = "\n".join(str(path) for path in missing)
                create_missing = messagebox.askyesno(
                    "Willy Repository Settings",
                    f"One or more folders do not exist yet.\n\n{missing_text}\n\nDo you want Willy to create them?",
                    parent=window,
                )
                if not create_missing:
                    status.configure(
                        text="Choose existing folders, or click Save again if you want Willy to create them."
                    )
                    return

            repo_private = privacy_var.get().startswith("Private repo")
            status.configure(text="Saving repository settings...")
            window.update_idletasks()
            try:
                message = configure_repository(
                    paths,
                    orca_user_dir=orca_text,
                    repo_path=repo_text,
                    remote=remote_var.get(),
                    branch=branch_var.get(),
                    repo_private=repo_private,
                    create_missing=create_missing,
                    initialize_repo=init_var.get(),
                    validate_remote=validate_var.get(),
                )
            except Exception as exc:
                message = f"Could not save repository settings:\n{exc}"
                write_event(
                    paths,
                    "statusbar_repository_config_failed",
                    error=str(exc),
                    traceback=traceback.format_exc(),
                    platform="win32",
                )
            status.configure(text=message)
            refresh_once()
            if message.startswith("Repository configured:"):
                window.after(900, window.destroy)

        ttk.Button(buttons, text="Clear Remote", command=clear_remote).pack(side=LEFT)
        ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side=RIGHT)
        ttk.Button(buttons, text="Save", command=save, style="RepoAccent.TButton").pack(side=RIGHT, padx=(0, 8))

        window.lift()
        window.focus_force()
        window.mainloop()

    def show_settings_window() -> None:
        from tkinter import BOTH, BooleanVar, Canvas, Frame, Label, StringVar, Tk, messagebox, ttk

        config = load_config(paths)
        startup_was_enabled = _startup_enabled(paths, config)

        window = Tk()
        window.title(f"Willy Settings - v{__version__}")
        window.geometry("980x760")
        window.minsize(860, 640)
        window.configure(bg="#101820")
        window.attributes("-topmost", True)
        window.after(700, lambda: window.attributes("-topmost", False))

        palette = {
            "bg": "#101820",
            "panel": "#f8f3ea",
            "card": "#fffdf8",
            "ink": "#17202a",
            "muted": "#65717d",
            "line": "#dfd6c8",
            "accent": "#176b5b",
            "accent_hover": "#0f574a",
            "danger": "#9f3a38",
        }

        style = ttk.Style(window)
        style.theme_use("clam")
        style.configure("Willy.TEntry", fieldbackground="#ffffff", bordercolor=palette["line"], padding=8)
        style.configure("Willy.TCombobox", fieldbackground="#ffffff", padding=8)
        style.configure(
            "Willy.TCheckbutton",
            background=palette["card"],
            foreground=palette["ink"],
            font=("Segoe UI", 10),
        )
        style.configure("Willy.TButton", padding=(14, 8), font=("Segoe UI", 10))
        style.configure(
            "Accent.TButton",
            padding=(16, 9),
            font=("Segoe UI", 10, "bold"),
            foreground="#ffffff",
            background=palette["accent"],
        )
        style.map("Accent.TButton", background=[("active", palette["accent_hover"])])

        shell = Frame(window, bg=palette["bg"])
        shell.pack(fill=BOTH, expand=True, padx=22, pady=22)

        header = Frame(shell, bg=palette["bg"])
        header.pack(fill="x", pady=(0, 16))
        Label(
            header,
            text="Willy Settings",
            bg=palette["bg"],
            fg="#fff8ea",
            font=("Segoe UI Variable Display", 22, "bold"),
        ).pack(anchor="w")
        Label(
            header,
            text="One place for Git sync, watched project files, startup behavior, and tray preferences.",
            bg=palette["bg"],
            fg="#cbd6dd",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        footer = Frame(shell, bg=palette["bg"])
        footer.pack(side="bottom", fill="x", pady=(14, 0))

        scroll_shell = Frame(shell, bg=palette["panel"])
        scroll_shell.pack(side="top", fill=BOTH, expand=True)

        canvas = Canvas(scroll_shell, bg=palette["panel"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(scroll_shell, orient="vertical", command=canvas.yview)
        content = Frame(canvas, bg=palette["panel"])
        content_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def configure_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def stretch_content(event) -> None:
            canvas.itemconfigure(content_id, width=event.width)

        content.bind("<Configure>", configure_scroll_region)
        canvas.bind("<Configure>", stretch_content)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill=BOTH, expand=True)
        scrollbar.pack(side="right", fill="y")

        def on_mousewheel(event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel)

        status_var = StringVar(value="Edit paths directly. Native folder dialogs are intentionally not used here.")
        orca_var = StringVar(value=str(config.orca_user_dir))
        repo_var = StringVar(value=str(config.repo_path))
        remote_var = StringVar(value=config.remote or remote_url(config.repo_path) or "")
        branch_var = StringVar(value=current_branch(config.repo_path) or config.branch or "main")
        asset_var = StringVar(value=str(config.asset_dirs[0]) if config.asset_dirs else "")
        debounce_var = StringVar(value=str(config.debounce_seconds))
        max_batch_var = StringVar(value=str(config.max_batch_seconds))
        privacy_var = StringVar(value="private" if config.repo_private else "public")
        initialize_var = BooleanVar(value=True)
        validate_remote_var = BooleanVar(value=False)
        protect_var = BooleanVar(value=config.protect_from_bamboo_poachers)
        startup_var = BooleanVar(value=startup_was_enabled)
        welcome_var = BooleanVar(value=config.show_tray_welcome)

        def card(title: str, subtitle: str) -> Frame:
            outer = Frame(content, bg=palette["panel"])
            outer.pack(fill="x", padx=18, pady=(0, 16))
            inner = Frame(outer, bg=palette["card"], highlightbackground=palette["line"], highlightthickness=1)
            inner.pack(fill="x")
            body = Frame(inner, bg=palette["card"])
            body.pack(fill="x", padx=20, pady=18)
            Label(body, text=title, bg=palette["card"], fg=palette["ink"], font=("Segoe UI", 14, "bold")).pack(
                anchor="w"
            )
            Label(
                body,
                text=subtitle,
                bg=palette["card"],
                fg=palette["muted"],
                font=("Segoe UI", 9),
                wraplength=860,
                justify="left",
            ).pack(anchor="w", pady=(3, 14))
            return body

        def field(parent: Frame, label: str, variable: StringVar, hint: str = "") -> ttk.Entry:
            Label(parent, text=label, bg=palette["card"], fg=palette["ink"], font=("Segoe UI", 10, "bold")).pack(
                anchor="w"
            )
            entry = ttk.Entry(parent, textvariable=variable, style="Willy.TEntry")
            entry.pack(fill="x", pady=(5, 4))
            if hint:
                Label(
                    parent,
                    text=hint,
                    bg=palette["card"],
                    fg=palette["muted"],
                    font=("Segoe UI", 9),
                    wraplength=860,
                    justify="left",
                ).pack(anchor="w", pady=(0, 12))
            else:
                Frame(parent, height=10, bg=palette["card"]).pack(fill="x")
            return entry

        def button_row(parent: Frame, buttons: tuple[tuple[str, object], ...]) -> None:
            row = Frame(parent, bg=palette["card"])
            row.pack(fill="x", pady=(2, 12))
            for text, command in buttons:
                ttk.Button(row, text=text, command=command, style="Willy.TButton").pack(side="left", padx=(0, 8))

        paths_card = card(
            "Paths",
            "These folders define where Willy reads Orca data and where the Git repository lives.",
        )
        field(paths_card, "Orca profile directory", orca_var)
        button_row(
            paths_card,
            (
                ("Use Orca Default", lambda: orca_var.set(str(paths.default_orca_user_dir))),
                ("Use Repo Folder", lambda: orca_var.set(repo_var.get())),
            ),
        )
        field(paths_card, "Repository folder", repo_var)
        button_row(
            paths_card,
            (
                ("Use Orca Folder", lambda: repo_var.set(orca_var.get())),
                ("Use Orca Default", lambda: repo_var.set(str(paths.default_orca_user_dir))),
            ),
        )

        git_card = card(
            "Git Sync",
            "Configure origin, branch, initialization, and whether remote access should be tested before saving.",
        )
        field(git_card, "Origin remote", remote_var, "Leave empty if this machine should only keep a local repo.")
        button_row(git_card, (("Clear Remote", lambda: remote_var.set("")),))
        two_columns = Frame(git_card, bg=palette["card"])
        two_columns.pack(fill="x", pady=(0, 12))
        left = Frame(two_columns, bg=palette["card"])
        left.pack(side="left", fill="x", expand=True, padx=(0, 10))
        right = Frame(two_columns, bg=palette["card"])
        right.pack(side="left", fill="x", expand=True, padx=(10, 0))
        field(left, "Branch", branch_var)
        Label(right, text="Privacy", bg=palette["card"], fg=palette["ink"], font=("Segoe UI", 10, "bold")).pack(
            anchor="w"
        )
        ttk.Combobox(
            right,
            textvariable=privacy_var,
            values=("public", "private"),
            state="readonly",
            style="Willy.TCombobox",
        ).pack(fill="x", pady=(5, 4))
        Label(
            right,
            text="public redacts sensitive fields; private keeps them in commits.",
            bg=palette["card"],
            fg=palette["muted"],
            font=("Segoe UI", 9),
            wraplength=400,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))
        ttk.Checkbutton(
            git_card,
            text="Initialize Git repo if needed",
            variable=initialize_var,
            style="Willy.TCheckbutton",
        ).pack(anchor="w", pady=(0, 6))
        ttk.Checkbutton(
            git_card,
            text="Validate remote access before saving",
            variable=validate_remote_var,
            style="Willy.TCheckbutton",
        ).pack(anchor="w")

        files_card = card(
            "Files & Projects",
            "Willy can also track .3mf and .stl files inside one project folder under the repo.",
        )
        field(files_card, "Tracked files/projects folder", asset_var)
        button_row(
            files_card,
            (
                ("Use Suggested", lambda: asset_var.set(str(Path(repo_var.get().strip().strip('"')) / "projects"))),
                ("Use Repo Folder", lambda: asset_var.set(repo_var.get())),
                ("Clear", lambda: asset_var.set("")),
            ),
        )

        behavior_card = card(
            "Behavior",
            "Timing, startup, tray onboarding, and optional protection assets.",
        )
        timing = Frame(behavior_card, bg=palette["card"])
        timing.pack(fill="x", pady=(0, 12))
        debounce_col = Frame(timing, bg=palette["card"])
        debounce_col.pack(side="left", fill="x", expand=True, padx=(0, 10))
        batch_col = Frame(timing, bg=palette["card"])
        batch_col.pack(side="left", fill="x", expand=True, padx=(10, 0))
        field(debounce_col, "Debounce seconds", debounce_var, "Wait this long after a file change before saving.")
        field(batch_col, "Max batch seconds", max_batch_var, "Maximum time to group rapid file changes.")
        ttk.Checkbutton(
            behavior_card,
            text="Start Willy tray when Windows starts",
            variable=startup_var,
            style="Willy.TCheckbutton",
        ).pack(anchor="w", pady=(0, 6))
        ttk.Checkbutton(
            behavior_card,
            text="Show tray welcome popup on startup",
            variable=welcome_var,
            style="Willy.TCheckbutton",
        ).pack(anchor="w", pady=(0, 6))
        ttk.Checkbutton(
            behavior_card,
            text="Protect from bamboo poachers",
            variable=protect_var,
            style="Willy.TCheckbutton",
        ).pack(anchor="w")

        Label(
            footer,
            textvariable=status_var,
            bg=palette["bg"],
            fg="#dce7ed",
            font=("Segoe UI", 9),
            wraplength=650,
            justify="left",
        ).pack(side="left", fill="x", expand=True)

        def parse_int(value: str, label: str) -> int | None:
            try:
                parsed = int(value.strip())
            except ValueError:
                status_var.set(f"{label} must be a whole number.")
                return None
            if parsed < 0:
                status_var.set(f"{label} cannot be negative.")
                return None
            return parsed

        def save() -> None:
            orca_text = orca_var.get().strip().strip('"')
            repo_text = repo_var.get().strip().strip('"')
            asset_text = asset_var.get().strip().strip('"')
            remote_text = remote_var.get().strip()
            if not orca_text or not repo_text:
                status_var.set("Orca profile directory and repository folder are required.")
                return
            debounce = parse_int(debounce_var.get(), "Debounce seconds")
            if debounce is None:
                return
            max_batch = parse_int(max_batch_var.get(), "Max batch seconds")
            if max_batch is None:
                return

            missing = [
                Path(value).expanduser()
                for value in (orca_text, repo_text, asset_text)
                if value and not Path(value).expanduser().exists()
            ]
            create_missing = True
            if missing:
                missing_text = "\n".join(str(path) for path in missing)
                create_missing = messagebox.askyesno(
                    "Willy Settings",
                    f"One or more folders do not exist yet.\n\n{missing_text}\n\nDo you want Willy to create them?",
                    parent=window,
                )
                if not create_missing:
                    status_var.set(
                        "Choose existing folders, clear the optional project folder, or save again to create."
                    )
                    return

            repo_path = Path(repo_text).expanduser().resolve()
            old_repo = config.repo_path.expanduser().resolve()
            old_remote = (config.remote or remote_url(config.repo_path) or "").strip()
            repo_changed = repo_path != old_repo
            remote_changed = remote_text != old_remote
            validate_remote_now = validate_remote_var.get() or bool(remote_text and (repo_changed or remote_changed))
            download_remote = False
            if remote_text and validate_remote_now:
                validation_cwd = repo_path if repo_path.exists() else repo_path.parent
                if not validation_cwd.exists():
                    validation_cwd = Path.home()
                try:
                    status_var.set("Checking Git remote access...")
                    window.update_idletasks()
                    validate_remote_access(validation_cwd, remote_text)
                    refs = remote_refs(validation_cwd, remote_text)
                except Exception as exc:
                    messagebox.showwarning(
                        "Willy Git Remote",
                        "Willy could not access this Git remote.\n\n"
                        f"{remote_text}\n\n"
                        f"{exc}\n\n"
                        "Check the URL, permissions, SSH key, or token, then validate again.",
                        parent=window,
                    )
                    status_var.set("Remote validation failed. Fix the remote or permissions before saving.")
                    return

                if refs and repo_changed:
                    download_remote = messagebox.askyesno(
                        "Willy Git Remote",
                        "Remote access is OK and the remote already has content.\n\n"
                        f"Branches found: {len(refs)}\n\n"
                        "Do you want Willy to download/clone that content into the selected repository folder?",
                        parent=window,
                    )
                elif not refs:
                    messagebox.showinfo(
                        "Willy Git Remote",
                        "Remote access is OK, but no branches were found there yet.\n"
                        "Willy will configure the remote and push when there is something to sync.",
                        parent=window,
                    )

            try:
                message = configure_repository(
                    paths,
                    orca_user_dir=orca_text,
                    repo_path=repo_text,
                    remote=remote_text,
                    branch=branch_var.get(),
                    repo_private=privacy_var.get() == "private",
                    asset_dirs=(asset_text,) if asset_text else (),
                    debounce_seconds=debounce,
                    max_batch_seconds=max_batch,
                    protect_from_bamboo_poachers=protect_var.get(),
                    tray_enabled=startup_var.get(),
                    show_tray_welcome=welcome_var.get(),
                    create_missing=create_missing,
                    initialize_repo=initialize_var.get(),
                    validate_remote=validate_remote_now,
                    download_remote=download_remote,
                )
                if startup_var.get() != startup_was_enabled:
                    _set_startup_enabled(paths, load_config(paths), startup_var.get())
            except Exception as exc:
                message = f"Could not save settings:\n{exc}"
                write_event(
                    paths,
                    "statusbar_settings_save_failed",
                    error=str(exc),
                    traceback=traceback.format_exc(),
                    platform="win32",
                )
            status_var.set(message)
            refresh_once()
            if message.startswith("Repository configured:"):
                window.after(900, window.destroy)

        ttk.Button(footer, text="Cancel", command=window.destroy, style="Willy.TButton").pack(side="right")
        ttk.Button(footer, text="Save Settings", command=save, style="Accent.TButton").pack(side="right", padx=(0, 10))

        window.lift()
        window.focus_force()
        window.mainloop()

    def configure_project_folder_action(icon_obj, item) -> None:
        open_repository_window_once("menu_project_folder")

    def configure_repository_action(icon_obj, item) -> None:
        open_repository_window_once("menu")

    def toggle_startup(icon_obj, item) -> None:
        write_event(
            paths,
            "statusbar_action",
            action="toggle_startup",
            phase=state["snapshot"].phase,
            platform="win32",
        )
        config = load_config(paths)
        enabled = _startup_enabled(paths, config)
        if enabled:
            confirmed = _windows_message_box(
                "Willy Startup",
                "Disable Willy tray on system start?\n"
                "You will need to run `willy start` and `willy statusbar` manually.",
                warning=True,
                yes_no=True,
            )
            if not confirmed:
                return
        try:
            message = _set_startup_enabled(paths, config, not enabled)
        except Exception as exc:
            message = f"Could not update tray startup:\n{exc}"
            show_message("Willy Startup", message, warning=True)
            return
        refresh_once()
        show_message("Willy Startup", message)

    def quit_tray(icon_obj, item) -> None:
        stop_event.set()
        _stop_embedded_daemon(paths)
        icon_obj.stop()

    def startup_title(item) -> str:
        enabled = _startup_enabled(paths, load_config(paths))
        return "Disable Willy tray on system start..." if enabled else "Enable Willy tray on system start"

    refresh_thread: threading.Thread | None = None
    open_config_thread: threading.Thread | None = None

    def setup_icon(icon_obj) -> None:
        nonlocal open_config_thread, refresh_thread
        write_event(paths, "statusbar_setup_begin", platform="win32")
        icon_obj.visible = True
        refresh_once()
        refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
        refresh_thread.start()
        open_config_thread = threading.Thread(
            target=open_config_request_loop,
            name="willy-tray-open-config",
            daemon=True,
        )
        open_config_thread.start()
        threading.Thread(target=show_welcome_window, name="willy-tray-welcome", daemon=True).start()
        write_event(paths, "statusbar_setup_complete", platform="win32")

    menu = pystray.Menu(
        pystray.MenuItem(f"Willy v{__version__}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda item: state["snapshot"].summary, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Detailed Status...", show_details),
        pystray.MenuItem("Force Sync / Download", do_force_sync),
        pystray.MenuItem("Settings...", configure_repository_action),
        pystray.MenuItem("Files / Projects Settings...", configure_project_folder_action),
        pystray.MenuItem(startup_title, toggle_startup),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Willy Tray", quit_tray),
    )
    icon = pystray.Icon("willy", tray_image(state["snapshot"].phase), state["snapshot"].summary, menu)
    write_event(paths, "statusbar_started", platform="win32")
    try:
        write_event(paths, "statusbar_run_enter", platform="win32")
        icon.run(setup=setup_icon)
    finally:
        write_event(paths, "statusbar_run_exit", platform="win32")
        stop_event.set()
        if refresh_thread is not None:
            refresh_thread.join(timeout=2)
        if open_config_thread is not None:
            open_config_thread.join(timeout=2)
        _stop_embedded_daemon(paths)
        _release_windows_tray_mutex()


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
