import sys
from pathlib import Path
from types import SimpleNamespace

from willy.config import WillyConfig, WillyState, load_config, load_state, save_config, save_state
from willy.daemon import pid_is_running
from willy.git import run_git
from willy.paths import default_paths
from willy.statusbar import (
    _acquire_windows_tray_mutex,
    _copy_text_to_clipboard,
    _release_windows_tray_mutex,
    _request_existing_tray_open_config,
    _tray_open_config_request_mtime,
    _tray_open_config_request_path,
    clear_project_folder,
    configure_project_folder,
    configure_repository,
    dismiss_tray_welcome,
    force_sync,
    snapshot,
    suggested_project_folder,
)
from willy.tray_settings import choose_existing_directory, folder_dialog_initial_dir


def _configured_repo(tmp_path: Path):
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    repo.mkdir(parents=True)
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Willy Test")
    save_config(paths, WillyConfig(orca_user_dir=repo, repo_path=repo))
    return paths, repo


def test_snapshot_hidden_when_orca_is_not_running_and_nothing_is_pending(tmp_path, monkeypatch) -> None:
    paths, _repo = _configured_repo(tmp_path)
    monkeypatch.setattr("willy.statusbar.pid_is_running", lambda pid: False)

    current = snapshot(paths, is_orca_running_func=lambda: False)

    assert current.visible is True
    assert current.phase == "no pending"
    assert current.icon_title == "W"


def test_snapshot_visible_when_orca_is_not_running_but_changes_are_pending(tmp_path, monkeypatch) -> None:
    paths, repo = _configured_repo(tmp_path)
    profile = repo / "default" / "filament" / "ABS.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    monkeypatch.setattr("willy.statusbar.pid_is_running", lambda pid: False)

    current = snapshot(paths, is_orca_running_func=lambda: False)

    assert current.visible is True
    assert current.phase == "pending"
    assert current.icon_title == "W*"


def test_snapshot_visible_when_orca_is_not_running_but_sync_is_pending(tmp_path, monkeypatch) -> None:
    paths, repo = _configured_repo(tmp_path)
    remote = tmp_path / "remote.git"
    remote.mkdir()
    run_git(remote, "init", "--bare")
    run_git(repo, "remote", "add", "origin", str(remote))
    tracked = repo / "default" / "filament" / "ABS.json"
    tracked.parent.mkdir(parents=True)
    tracked.write_text('{"name": "ABS"}\n', encoding="utf-8")
    run_git(repo, "add", "default/filament/ABS.json")
    run_git(repo, "commit", "-m", "local only")
    monkeypatch.setattr("willy.statusbar.pid_is_running", lambda pid: False)

    current = snapshot(paths, is_orca_running_func=lambda: False)

    assert current.visible is True
    assert current.phase == "pending"
    assert current.icon_title == "W*"
    assert "Sync pending: yes (upstream not configured)" in current.details


def test_snapshot_shows_saving_when_operation_is_active(tmp_path, monkeypatch) -> None:
    paths, _repo = _configured_repo(tmp_path)
    save_state(paths, WillyState(active_operation="saving", daemon_pid=123))
    monkeypatch.setattr("willy.statusbar.pid_is_running", lambda pid: True)

    current = snapshot(paths, is_orca_running_func=lambda: True)

    assert current.visible is True
    assert current.phase == "saving"
    assert current.icon_title == "W..."
    assert "Daemon: running" in current.details


def test_force_sync_saves_and_clears_operation(tmp_path) -> None:
    paths, repo = _configured_repo(tmp_path)
    profile = repo / "default" / "filament" / "PETG.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "PETG"}\n', encoding="utf-8")

    message = force_sync(paths)

    assert "Saved 1 file(s)." in message
    assert "Sync: no remote configured" in message
    assert load_state(paths).active_operation is None
    assert "PETG" in run_git(repo, "show", "HEAD:default/filament/PETG.json").stdout


def test_configure_project_folder_saves_folder_inside_repo(tmp_path) -> None:
    paths, repo = _configured_repo(tmp_path)
    folder = repo / "projects"

    message = configure_project_folder(paths, folder)

    assert "Files and projects folder configured" in message
    assert load_config(paths).asset_dirs == (folder,)
    assert folder.exists()


def test_configure_project_folder_can_reject_missing_folder(tmp_path) -> None:
    paths, repo = _configured_repo(tmp_path)
    folder = repo / "missing-projects"

    message = configure_project_folder(paths, folder, create_missing=False)

    assert "Folder does not exist" in message
    assert load_config(paths).asset_dirs == ()
    assert not folder.exists()


def test_configure_project_folder_rejects_folder_outside_repo(tmp_path) -> None:
    paths, _repo = _configured_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    message = configure_project_folder(paths, outside)

    assert "Choose a folder inside the sync repo" in message
    assert load_config(paths).asset_dirs == ()


def test_clear_project_folder_removes_configured_folder(tmp_path) -> None:
    paths, repo = _configured_repo(tmp_path)
    folder = repo / "projects"
    save_config(paths, WillyConfig(orca_user_dir=repo, repo_path=repo, asset_dirs=(folder,)))

    message = clear_project_folder(paths)

    assert message == "Files and projects folder cleared."
    assert load_config(paths).asset_dirs == ()


def test_configure_repository_saves_repo_remote_branch_and_privacy(tmp_path) -> None:
    paths = default_paths(tmp_path / "home")
    orca_dir = tmp_path / "orca"
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    remote.mkdir()
    run_git(remote, "init", "--bare")

    message = configure_repository(
        paths,
        orca_user_dir=orca_dir,
        repo_path=repo,
        remote=str(remote),
        branch="main",
        repo_private=True,
        validate_remote=True,
    )

    config = load_config(paths)
    assert "Repository configured" in message
    assert config.orca_user_dir == orca_dir
    assert config.repo_path == repo
    assert config.remote == str(remote)
    assert config.branch == "main"
    assert config.repo_private is True
    assert (repo / ".git").exists()
    assert run_git(repo, "remote", "get-url", "origin").stdout.strip() == str(remote)


def test_configure_repository_saves_extended_settings(tmp_path) -> None:
    paths = default_paths(tmp_path / "home")
    repo = tmp_path / "repo"
    asset_dir = repo / "projects"

    message = configure_repository(
        paths,
        orca_user_dir=repo,
        repo_path=repo,
        remote="",
        branch="main",
        repo_private=False,
        asset_dirs=(asset_dir,),
        debounce_seconds=7,
        max_batch_seconds=42,
        protect_from_bamboo_poachers=True,
        tray_enabled=True,
        show_tray_welcome=False,
    )

    config = load_config(paths)
    assert "Repository configured" in message
    assert config.asset_dirs == (asset_dir,)
    assert config.debounce_seconds == 7
    assert config.max_batch_seconds == 42
    assert config.protect_from_bamboo_poachers is True
    assert config.tray_enabled is True
    assert config.show_tray_welcome is False
    assert asset_dir.exists()


def test_configure_repository_can_download_remote_content(tmp_path) -> None:
    paths = default_paths(tmp_path / "home")
    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    repo = tmp_path / "downloaded"
    remote.mkdir()
    source.mkdir()
    run_git(remote, "init", "--bare")
    run_git(source, "init")
    run_git(source, "config", "user.email", "test@example.com")
    run_git(source, "config", "user.name", "Willy Test")
    (source / "profile.json").write_text("{}\n", encoding="utf-8")
    run_git(source, "add", "profile.json")
    run_git(source, "commit", "-m", "initial")
    run_git(source, "branch", "-M", "main")
    run_git(source, "remote", "add", "origin", str(remote))
    run_git(source, "push", "-u", "origin", "main")

    message = configure_repository(
        paths,
        orca_user_dir=repo,
        repo_path=repo,
        remote=str(remote),
        branch="main",
        repo_private=False,
        validate_remote=True,
        download_remote=True,
    )

    assert "Repository configured" in message
    assert (repo / "profile.json").exists()
    assert load_config(paths).repo_path == repo


def test_configure_repository_rejects_missing_folder_when_create_is_false(tmp_path) -> None:
    paths = default_paths(tmp_path / "home")
    orca_dir = tmp_path / "missing-orca"
    repo = tmp_path / "missing-repo"

    message = configure_repository(
        paths,
        orca_user_dir=orca_dir,
        repo_path=repo,
        remote="",
        branch="main",
        repo_private=False,
        create_missing=False,
    )

    assert "Orca profile directory does not exist" in message
    assert not orca_dir.exists()
    assert not repo.exists()


def test_suggested_project_folder_uses_projects_under_repo(tmp_path) -> None:
    paths, repo = _configured_repo(tmp_path)
    config = load_config(paths)

    assert suggested_project_folder(config) == repo / "projects"


def test_folder_dialog_initial_dir_prefers_existing_current_path(tmp_path) -> None:
    current = tmp_path / "current"
    fallback = tmp_path / "fallback"
    current.mkdir()
    fallback.mkdir()

    assert folder_dialog_initial_dir(current, fallback) == current


def test_folder_dialog_initial_dir_uses_existing_fallback(tmp_path) -> None:
    fallback = tmp_path / "fallback"
    fallback.mkdir()

    assert folder_dialog_initial_dir(tmp_path / "missing", fallback) == fallback


def test_choose_existing_directory_uses_system_dialog(tmp_path) -> None:
    fallback = tmp_path / "fallback"
    selected = tmp_path / "selected"
    fallback.mkdir()
    selected.mkdir()
    calls = []

    class FakeFileDialog:
        @staticmethod
        def askdirectory(**kwargs):
            calls.append(kwargs)
            return str(selected)

    assert choose_existing_directory(
        FakeFileDialog,
        parent="window",
        title="Choose folder",
        current=tmp_path / "missing",
        fallback=fallback,
    ) == str(selected)
    assert calls == [
        {
            "parent": "window",
            "title": "Choose folder",
            "initialdir": str(fallback),
            "mustexist": True,
        }
    ]


def test_dismiss_tray_welcome_persists_preference(tmp_path) -> None:
    paths, _repo = _configured_repo(tmp_path)

    dismiss_tray_welcome(paths)

    assert load_config(paths).show_tray_welcome is False


def test_acquire_windows_tray_mutex_rejects_duplicate(monkeypatch) -> None:
    class FakeKernel32:
        def __init__(self) -> None:
            self.closed = []

        def CreateMutexW(self, _attrs, _initial_owner, _name):
            return 99

        def GetLastError(self):
            return 183

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return 1

    fake_kernel32 = FakeKernel32()
    fake_ctypes = SimpleNamespace(windll=SimpleNamespace(kernel32=fake_kernel32))
    monkeypatch.setattr("willy.statusbar.sys.platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert _acquire_windows_tray_mutex() is False
    assert fake_kernel32.closed == [99]


def test_release_windows_tray_mutex_closes_handle(monkeypatch) -> None:
    class FakeKernel32:
        def __init__(self) -> None:
            self.closed = []
            self.last_error = 0

        def CreateMutexW(self, _attrs, _initial_owner, _name):
            return 77

        def GetLastError(self):
            return self.last_error

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return 1

    fake_kernel32 = FakeKernel32()
    fake_ctypes = SimpleNamespace(windll=SimpleNamespace(kernel32=fake_kernel32))
    monkeypatch.setattr("willy.statusbar.sys.platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert _acquire_windows_tray_mutex() is True
    _release_windows_tray_mutex()
    assert fake_kernel32.closed == [77]


def test_request_existing_tray_open_config_writes_request_file(tmp_path) -> None:
    paths = default_paths(tmp_path)

    _request_existing_tray_open_config(paths)

    request_path = _tray_open_config_request_path(paths)
    assert request_path.exists()
    assert request_path.read_text(encoding="utf-8")
    assert _tray_open_config_request_mtime(paths) is not None


def test_copy_text_to_clipboard_uses_pbcopy_on_macos(monkeypatch) -> None:
    calls = []

    def fake_run(args, *, input, text, check):
        calls.append((args, input, text, check))
        return None

    monkeypatch.setattr("willy.statusbar.sys.platform", "darwin")
    monkeypatch.setattr("subprocess.run", fake_run)

    _copy_text_to_clipboard("hello")

    assert calls == [(["pbcopy"], "hello", True, True)]


def test_pid_is_running_uses_native_windows_process_api(monkeypatch) -> None:
    class FakeFunction:
        def __init__(self, func):
            self.func = func
            self.restype = None

        def __call__(self, *args):
            return self.func(*args)

    class FakeKernel32:
        def __init__(self) -> None:
            self.closed = []
            self.OpenProcess = FakeFunction(lambda _access, _inherit, _pid: 123)
            self.GetExitCodeProcess = FakeFunction(self._get_exit_code)
            self.CloseHandle = FakeFunction(lambda handle: self.closed.append(handle) or 1)

        def _get_exit_code(self, _handle, exit_code):
            exit_code._obj.value = 259
            return 1

    fake_kernel32 = FakeKernel32()
    fake_ctypes = SimpleNamespace(
        windll=SimpleNamespace(kernel32=fake_kernel32),
        c_void_p=object,
        c_ulong=lambda: SimpleNamespace(value=0),
        byref=lambda value: SimpleNamespace(_obj=value),
    )

    monkeypatch.setattr("willy.daemon.sys.platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    assert pid_is_running(123) is True
    assert fake_kernel32.closed == [123]


def test_run_git_hides_console_on_windows(tmp_path: Path, monkeypatch) -> None:
    calls = []

    class Result:
        returncode = 0
        stdout = "true\n"
        stderr = ""

    def fake_run(command, *, cwd, text, capture_output, timeout, env, creationflags):
        calls.append((command, cwd, text, capture_output, timeout, env, creationflags))
        return Result()

    monkeypatch.setattr("willy.git.sys.platform", "win32")
    monkeypatch.setattr("willy.git.subprocess.CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr("willy.git.subprocess.run", fake_run)
    monkeypatch.setattr("willy.git._resolve_git_executable", lambda: "git.exe")

    assert run_git(tmp_path, "rev-parse", "--is-inside-work-tree").stdout == "true\n"
    assert calls == [
        (
            ("git.exe", "rev-parse", "--is-inside-work-tree"),
            tmp_path,
            True,
            True,
            60,
            None,
            0x08000000,
        )
    ]
