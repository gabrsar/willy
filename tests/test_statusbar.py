from pathlib import Path

from willy.config import WillyConfig, WillyState, load_state, save_config, save_state
from willy.git import run_git
from willy.paths import default_paths
from willy.statusbar import force_sync, snapshot


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

    assert current.visible is False
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
