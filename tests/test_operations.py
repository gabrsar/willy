from pathlib import Path

from willy.git import config_get_local, run_git
from willy.operations import save_profile_changes, sync_repo, unsaved_summary
from willy.redact import REDACTED


def test_save_profile_changes_commits_json_and_sets_identity(tmp_path: Path) -> None:
    run_git(tmp_path, "init")
    profile = tmp_path / "default" / "filament" / "ABS.json"
    sidecar = tmp_path / "default" / "filament" / "ABS.info"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    sidecar.write_text("setting_id = PFUS\n", encoding="utf-8")

    result = save_profile_changes(tmp_path, description="manual test")

    assert result.saved
    assert result.count == 1
    author = run_git(tmp_path, "log", "-1", "--pretty=%an <%ae>").stdout.strip()
    assert author == "Willy <willy@local>"
    assert config_get_local(tmp_path, "user.name") == "Willy"
    assert config_get_local(tmp_path, "user.email") == "willy@local"
    status = run_git(tmp_path, "status", "--porcelain").stdout
    assert "ABS.json" not in status
    assert "ABS.info" in status


def test_save_profile_changes_clean_repo_returns_unsaved(tmp_path: Path) -> None:
    run_git(tmp_path, "init")

    result = save_profile_changes(tmp_path, description="nothing")

    assert not result.saved
    assert result.count == 0


def test_save_profile_changes_redacts_sensitive_json_by_default(tmp_path: Path) -> None:
    run_git(tmp_path, "init")
    profile = tmp_path / "default" / "machine" / "Printer.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        '{"name": "Printer", "print_host": "192.168.1.42", "printhost_apikey": "secret-key"}\n',
        encoding="utf-8",
    )

    result = save_profile_changes(tmp_path, description="public save")

    assert result.saved
    blob = run_git(tmp_path, "show", "HEAD:default/machine/Printer.json").stdout
    assert REDACTED in blob
    assert "192.168.1.42" not in blob
    assert "secret-key" not in blob
    assert "secret-key" in profile.read_text(encoding="utf-8")
    assert "*.json filter=willy-redact" in run_git(tmp_path, "show", "HEAD:.gitattributes").stdout


def test_save_profile_changes_keeps_sensitive_json_when_allowed(tmp_path: Path) -> None:
    run_git(tmp_path, "init")
    profile = tmp_path / "default" / "machine" / "Printer.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        '{"name": "Printer", "print_host": "192.168.1.42", "printhost_apikey": "secret-key"}\n',
        encoding="utf-8",
    )

    result = save_profile_changes(tmp_path, description="private save", allow_sensitive=True)

    assert result.saved
    blob = run_git(tmp_path, "show", "HEAD:default/machine/Printer.json").stdout
    assert "192.168.1.42" in blob
    assert "secret-key" in blob
    assert run_git(tmp_path, "show", "HEAD:.gitattributes", check=False).returncode != 0


def test_unsaved_summary_counts_user_id_profiles(tmp_path: Path) -> None:
    run_git(tmp_path, "init")
    profile = tmp_path / "2765349417" / "process" / "Fast.json"
    sidecar = tmp_path / "2765349417" / "process" / "Fast.info"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}\n", encoding="utf-8")
    sidecar.write_text("setting_id = PPUS\n", encoding="utf-8")

    summary = unsaved_summary(tmp_path)

    assert summary.count == 1
    assert summary.paths == [Path("2765349417/process/Fast.json")]


def test_sync_repo_without_changes_still_pushes_existing_commit(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    remote.mkdir()
    repo.mkdir()
    run_git(remote, "init", "--bare")
    run_git(repo, "init")
    run_git(repo, "branch", "-M", "main")
    run_git(repo, "remote", "add", "origin", str(remote))
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Willy Test")
    (repo / "default").mkdir()
    (repo / "default" / "profile.json").write_text("{}\n", encoding="utf-8")
    run_git(repo, "add", "default/profile.json")
    run_git(repo, "commit", "-m", "initial")

    assert sync_repo(repo) == "synced"
    assert sync_repo(repo) == "synced"
