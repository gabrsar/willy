from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from datetime import datetime

from willy.config import WillyConfig, load_config, load_state, save_config, save_state
from willy.daemon import pid_is_running
from willy.git import current_branch, is_repo, last_commit, remote_url, status_porcelain, sync_delta
from willy.launchd import disable_launchd, enable_launchd, launchd_enabled
from willy.logging import setup_logging, write_event
from willy.operations import save_profile_changes, sync_repo, unsaved_summary
from willy.orca import is_orca_running
from willy.paths import WillyPaths, default_paths


@dataclass(frozen=True)
class StatusSnapshot:
    visible: bool
    phase: str
    icon_title: str
    summary: str
    details: str


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
    unsaved = unsaved_summary(config.repo_path) if repo_ready else None
    unsaved_count = unsaved.count if unsaved else 0
    delta = sync_delta(config.repo_path) if repo_ready else None
    sync_pending = bool(delta and delta.pending)
    daemon_running = pid_is_running(state.daemon_pid)
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
    details = "\n".join(
        [
            f"Status: {summary}",
            f"Orca running: {'yes' if orca_running else 'no'}",
            f"Daemon: {'running' if daemon_running else 'not running'}",
            f"Repo: {config.repo_path}",
            f"Branch: {branch or 'unknown'}",
            f"Remote: {remote or 'none'}",
            f"Uncommitted changes: {len(changes)}",
            f"Unsaved configs: {unsaved_count}",
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
    return StatusSnapshot(
        visible=orca_running or phase != "no pending",
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
            description="Manual status bar sync",
            allow_sensitive=bool(config.repo_private),
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


def _set_launchd_enabled(paths: WillyPaths, config: WillyConfig, enabled: bool) -> str:
    if enabled:
        plist_path = enable_launchd(paths)
        save_config(paths, replace(config, launchd_enabled=True))
        return f"Willy daemon will start on login.\n{plist_path}"
    plist_path = disable_launchd(paths)
    save_config(paths, replace(config, launchd_enabled=False))
    return f"Willy daemon startup disabled.\nStart it manually with: willy start\n{plist_path}"


def run_statusbar(*, poll_seconds: float = 2.0) -> None:
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
        raise RuntimeError("The macOS status bar requires PyObjC. Run `make install` and try again.") from exc

    paths = default_paths()
    setup_logging(paths)

    class StatusBarController(NSObject):
        def initWithPollSeconds_(self, seconds):
            self = objc.super(StatusBarController, self).init()
            if self is None:
                return None
            self.poll_seconds = seconds
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
            self.addMenuItem(menu, "Detailed Status...", "showDetails:")
            self.addMenuItem(menu, "Force Sync / Download", "forceSync:")
            config = load_config(paths)
            enabled = launchd_enabled(paths) or config.launchd_enabled
            title = "Disable daemon on system start..." if enabled else "Enable daemon on system start"
            self.addMenuItem(menu, title, "toggleLaunchd:")
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

        def forceSync_(self, _sender):
            try:
                message = force_sync(paths)
            except Exception as exc:
                message = f"Force sync failed:\n{exc}"
            self.refresh_(None)
            self.showMessage_title_style_(message, "Willy Sync", NSInformationalAlertStyle)

        def toggleLaunchd_(self, _sender):
            config = load_config(paths)
            enabled = launchd_enabled(paths) or config.launchd_enabled
            if enabled and not self.confirmDisableLaunchd():
                return
            try:
                message = _set_launchd_enabled(paths, config, not enabled)
            except Exception as exc:
                message = f"Could not update daemon startup:\n{exc}"
            self.refresh_(None)
            self.showMessage_title_style_(message, "Willy Startup", NSInformationalAlertStyle)

        def confirmDisableLaunchd(self):
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
            NSApplication.sharedApplication().terminate_(self)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = StatusBarController.alloc().initWithPollSeconds_(poll_seconds)
    controller.refresh_(None)
    write_event(paths, "statusbar_started")
    app.run()


def main() -> int:
    try:
        run_statusbar()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0
