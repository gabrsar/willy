from __future__ import annotations

import sys
import traceback
from pathlib import Path

from willy import __version__
from willy.config import load_config
from willy.git import current_branch, remote_refs, remote_url, validate_remote_access
from willy.logging import setup_logging, write_event
from willy.paths import WillyPaths, default_paths
from willy.statusbar import (
    _acquire_windows_tray_mutex,
    _asset_path,
    _request_existing_tray_open_config,
    _start_embedded_daemon,
    _stop_embedded_daemon,
    _tray_open_config_request_mtime,
    check_remote_on_load,
    force_sync,
    snapshot,
)
from willy.tray_settings import configure_repository
from willy.windows_startup import disable_windows_startup, enable_windows_startup, windows_startup_enabled


def _startup_enabled(paths: WillyPaths) -> bool:
    return windows_startup_enabled(paths)


def _set_startup_enabled(paths: WillyPaths, enabled: bool) -> str:
    if enabled:
        script_path = enable_windows_startup(paths)
        return f"Willy tray and daemon will start on login.\n{script_path}"
    script_path = disable_windows_startup(paths)
    return f"Willy tray startup disabled.\nStart manually with: willy start and willy statusbar\n{script_path}"


def run_windows_tray(*, poll_seconds: float, start_daemon: bool) -> None:
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QAction, QIcon
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QDialog,
            QFileDialog,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMenu,
            QMessageBox,
            QPushButton,
            QScrollArea,
            QSpinBox,
            QSystemTrayIcon,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:
        raise RuntimeError("The Windows tray settings UI requires PySide6. Run setup and rebuild Willy.") from exc

    paths = default_paths()
    setup_logging(paths)
    if not _acquire_windows_tray_mutex():
        _request_existing_tray_open_config(paths)
        write_event(paths, "statusbar_duplicate_instance", platform="win32", ui="qt")
        return
    if start_daemon:
        _start_embedded_daemon(paths)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)

    icon_path = _asset_path("assets", "icon.ico")
    if not icon_path.exists():
        icon_path = _asset_path("assets", "icon.png")
    tray = QSystemTrayIcon(QIcon(str(icon_path)), app)
    menu = QMenu()
    state = {"snapshot": snapshot(paths), "settings": None, "last_request": _tray_open_config_request_mtime(paths)}

    def show_status() -> None:
        state["snapshot"] = snapshot(paths)
        dialog = QDialog()
        dialog.setWindowTitle("Willy Status")
        dialog.resize(720, 460)
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(state["snapshot"].details)
        layout.addWidget(text)
        buttons = QHBoxLayout()
        copy = QPushButton("Copy")
        close = QPushButton("Close")
        buttons.addStretch(1)
        buttons.addWidget(copy)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(state["snapshot"].details))
        close.clicked.connect(dialog.close)
        dialog.exec()

    def run_force_sync() -> None:
        try:
            message = force_sync(paths)
        except Exception as exc:
            message = f"Force sync failed:\n{exc}"
        refresh()
        QMessageBox.information(None, "Willy Sync", message)

    def remote_check_on_load() -> None:
        message = check_remote_on_load(paths)
        refresh()
        if "available" in message or "failed" in message or "upstream" in message:
            tray.showMessage("Willy", message, QSystemTrayIcon.MessageIcon.Information, 8000)

    def line_with_browse(label: str, value: str, parent: QWidget) -> tuple[QLineEdit, QPushButton]:
        edit = QLineEdit(value)
        browse = QPushButton("Browse...")
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(browse)
        parent.layout().addRow(label, row)
        return edit, browse

    def open_settings() -> None:
        existing = state.get("settings")
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

        config = load_config(paths)
        dialog = QDialog()
        state["settings"] = dialog
        dialog.setWindowTitle(f"Willy Settings - v{__version__}")
        dialog.resize(900, 720)

        root = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        scroll.setWidget(body)
        root.addWidget(scroll)

        orca_edit, orca_browse = line_with_browse("Orca profile directory", str(config.orca_user_dir), body)
        repo_edit, repo_browse = line_with_browse("Repository folder", str(config.repo_path), body)
        asset_edit, asset_browse = line_with_browse(
            "Tracked files/projects folder",
            str(config.asset_dirs[0]) if config.asset_dirs else "",
            body,
        )
        remote_edit = QLineEdit(config.remote or remote_url(config.repo_path) or "")
        form.addRow("Git remote origin", remote_edit)
        branch_edit = QLineEdit(current_branch(config.repo_path) or config.branch or "main")
        form.addRow("Branch", branch_edit)
        privacy = QComboBox()
        privacy.addItems(["public", "private"])
        privacy.setCurrentText("private" if config.repo_private else "public")
        form.addRow("Privacy", privacy)
        debounce = QSpinBox()
        debounce.setRange(0, 3600)
        debounce.setValue(config.debounce_seconds)
        form.addRow("Debounce seconds", debounce)
        max_batch = QSpinBox()
        max_batch.setRange(0, 3600)
        max_batch.setValue(config.max_batch_seconds)
        form.addRow("Max batch seconds", max_batch)
        initialize = QCheckBox("Initialize Git repo if needed")
        initialize.setChecked(True)
        form.addRow("", initialize)
        validate_remote = QCheckBox("Validate remote access before saving")
        form.addRow("", validate_remote)
        startup = QCheckBox("Start Willy tray when Windows starts")
        startup.setChecked(_startup_enabled(paths))
        form.addRow("", startup)
        welcome = QCheckBox("Show tray welcome popup on startup")
        welcome.setChecked(config.show_tray_welcome)
        form.addRow("", welcome)
        protect = QCheckBox("Protect from bamboo poachers")
        protect.setChecked(config.protect_from_bamboo_poachers)
        form.addRow("", protect)
        status = QLabel("Choose folders with Browse or edit paths directly. Save validates read/write access.")
        status.setWordWrap(True)
        root.addWidget(status)

        buttons = QHBoxLayout()
        save_button = QPushButton("Save Settings")
        cancel_button = QPushButton("Cancel")
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        root.addLayout(buttons)

        def choose_folder(edit: QLineEdit, title: str, fallback: str | Path) -> None:
            current = Path(edit.text().strip().strip('"') or str(fallback)).expanduser()
            initial = current if current.exists() else Path(fallback).expanduser()
            selected = QFileDialog.getExistingDirectory(dialog, title, str(initial))
            if selected:
                edit.setText(selected)
                status.setText("Folder selected. Click Save Settings to apply it.")

        orca_browse.clicked.connect(
            lambda: choose_folder(orca_edit, "Choose Orca profile directory", paths.default_orca_user_dir)
        )
        repo_browse.clicked.connect(lambda: choose_folder(repo_edit, "Choose repository folder", config.repo_path))
        asset_browse.clicked.connect(
            lambda: choose_folder(
                asset_edit, "Choose tracked files/projects folder", repo_edit.text() or config.repo_path
            )
        )
        cancel_button.clicked.connect(dialog.close)

        def save_settings() -> None:
            orca_text = orca_edit.text().strip().strip('"')
            repo_text = repo_edit.text().strip().strip('"')
            asset_text = asset_edit.text().strip().strip('"')
            remote_text = remote_edit.text().strip()
            if not orca_text or not repo_text:
                status.setText("Orca profile directory and repository folder are required.")
                return
            missing = [
                Path(value).expanduser()
                for value in (orca_text, repo_text, asset_text)
                if value and not Path(value).expanduser().exists()
            ]
            create_missing = True
            if missing:
                missing_text = "\n".join(str(path) for path in missing)
                create_missing = (
                    QMessageBox.question(
                        dialog,
                        "Willy Settings",
                        f"One or more folders do not exist yet.\n\n{missing_text}\n\nDo you want Willy to create them?",
                    )
                    == QMessageBox.StandardButton.Yes
                )
                if not create_missing:
                    status.setText(
                        "Choose existing folders, clear the optional project folder, or save again to create."
                    )
                    return

            repo_path = Path(repo_text).expanduser().resolve()
            old_repo = config.repo_path.expanduser().resolve()
            old_remote = (config.remote or remote_url(config.repo_path) or "").strip()
            validate_remote_now = validate_remote.isChecked() or bool(
                remote_text and (repo_path != old_repo or remote_text != old_remote)
            )
            download_remote = False
            if remote_text and validate_remote_now:
                validation_cwd = repo_path if repo_path.exists() else repo_path.parent
                if not validation_cwd.exists():
                    validation_cwd = Path.home()
                try:
                    status.setText("Checking Git remote access...")
                    QApplication.processEvents()
                    validate_remote_access(validation_cwd, remote_text)
                    refs = remote_refs(validation_cwd, remote_text)
                except Exception as exc:
                    QMessageBox.warning(
                        dialog, "Willy Git Remote", f"Willy could not access this Git remote.\n\n{remote_text}\n\n{exc}"
                    )
                    status.setText("Remote validation failed. Fix the remote or permissions before saving.")
                    return
                if refs and repo_path != old_repo:
                    download_remote = (
                        QMessageBox.question(
                            dialog,
                            "Willy Git Remote",
                            "Remote access is OK and the remote already has content.\n\n"
                            f"Branches found: {len(refs)}\n\n"
                            "Download/clone that content into the selected repository folder?",
                        )
                        == QMessageBox.StandardButton.Yes
                    )

            try:
                message = configure_repository(
                    paths,
                    orca_user_dir=orca_text,
                    repo_path=repo_text,
                    remote=remote_text,
                    branch=branch_edit.text(),
                    repo_private=privacy.currentText() == "private",
                    asset_dirs=(asset_text,) if asset_text else (),
                    debounce_seconds=debounce.value(),
                    max_batch_seconds=max_batch.value(),
                    protect_from_bamboo_poachers=protect.isChecked(),
                    tray_enabled=startup.isChecked(),
                    show_tray_welcome=welcome.isChecked(),
                    create_missing=create_missing,
                    initialize_repo=initialize.isChecked(),
                    validate_remote=validate_remote_now,
                    download_remote=download_remote,
                )
                _set_startup_enabled(paths, startup.isChecked())
            except Exception as exc:
                message = f"Could not save settings:\n{exc}"
                write_event(
                    paths, "qt_settings_save_failed", error=str(exc), traceback=traceback.format_exc(), platform="win32"
                )
            status.setText(message)
            refresh()
            if message.startswith("Repository configured:"):
                dialog.close()

        save_button.clicked.connect(save_settings)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def refresh() -> None:
        current = snapshot(paths)
        state["snapshot"] = current
        tray.setToolTip(current.summary)

    def check_open_request() -> None:
        current_mtime = _tray_open_config_request_mtime(paths)
        if current_mtime is not None and current_mtime != state["last_request"]:
            state["last_request"] = current_mtime
            open_settings()

    def exit_tray() -> None:
        _stop_embedded_daemon(paths)
        tray.hide()
        app.quit()

    status_action = QAction("Status", menu)
    sync_action = QAction("Force Sync / Download", menu)
    settings_action = QAction("Settings", menu)
    exit_action = QAction("Exit", menu)
    status_action.triggered.connect(show_status)
    sync_action.triggered.connect(run_force_sync)
    settings_action.triggered.connect(open_settings)
    exit_action.triggered.connect(exit_tray)
    menu.addAction(status_action)
    menu.addAction(sync_action)
    menu.addAction(settings_action)
    menu.addSeparator()
    menu.addAction(exit_action)
    tray.setContextMenu(menu)
    tray.show()
    QTimer.singleShot(100, remote_check_on_load)

    refresh_timer = QTimer()
    refresh_timer.timeout.connect(refresh)
    refresh_timer.start(max(1, int(poll_seconds * 1000)))
    request_timer = QTimer()
    request_timer.timeout.connect(check_open_request)
    request_timer.start(500)

    write_event(paths, "statusbar_started", platform="win32", ui="qt")
    try:
        app.exec()
    finally:
        _stop_embedded_daemon(paths)
