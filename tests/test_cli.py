from typer.testing import CliRunner

from willy.cli import HELP_TEXT, app, main
from willy.config import load_config
from willy.errors import GitError
from willy.git import is_repo, remote_url, run_git
from willy.paths import default_paths


def test_help_text_starts_with_required_tldr() -> None:
    assert HELP_TEXT.startswith("TL;DR:\nsetup Connect OrcaSlicer profiles to Git")


def test_main_help_prints_required_tldr(capsys) -> None:
    exit_code = main(["--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.startswith("TL;DR:\nsetup Connect OrcaSlicer profiles to Git")


def test_status_command_runs_with_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Willy status" in result.output
    assert "Git repo: no" in result.output


def test_save_commits_trackable_json_only(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = home / "Library" / "Application Support" / "OrcaSlicer" / "user"
    profile = repo / "default" / "filament" / "ABS.json"
    sidecar = repo / "default" / "filament" / "ABS.info"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    sidecar.write_text("setting_id = PFUS\n", encoding="utf-8")
    monkeypatch.setattr("willy.cli.default_paths", lambda: default_paths(home))
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Willy Test")
    runner = CliRunner()

    result = runner.invoke(app, ["save", "first profile"])

    assert result.exit_code == 0
    assert "Saved 1 file(s)." in result.output
    status = run_git(repo, "status", "--porcelain").stdout
    assert "ABS.json" not in status
    assert "ABS.info" in status


def test_setup_initializes_repo_remote_backup_and_protection(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    profile = repo / "default" / "filament" / "ABS.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    remote = tmp_path / "remote.git"
    remote.mkdir()
    run_git(remote, "init", "--bare")
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.is_orca_running", lambda: False)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "setup",
            "--mode",
            "new",
            "--yes",
            "--remote",
            str(remote),
            "--protect-from-bamboo-poachers",
        ],
    )

    assert result.exit_code == 0
    assert "Backup created:" in result.output
    assert "Initialized Git repo." in result.output
    assert "Configured origin remote." in result.output
    assert "Added AGPL-3.0 protection assets." in result.output
    assert is_repo(repo)
    assert remote_url(repo) == str(remote)
    assert (repo / "LICENSE").exists()
    assert (repo / "README.md").exists()
    assert list(paths.backups_dir.glob("*/.willy-backup.json"))
    assert load_config(paths).remote == str(remote)


def test_main_formats_git_remote_error_without_traceback(tmp_path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    profile = repo / "default" / "filament" / "ABS.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.is_orca_running", lambda: False)

    def fail_remote(*args, **kwargs):
        raise GitError(
            "Git command failed",
            stderr=("ERROR: Repository not found.\nfatal: Could not read from remote repository.\n"),
        )

    monkeypatch.setattr("willy.cli.validate_remote_access", fail_remote)

    exit_code = main(["setup", "--mode", "new", "--yes", "--remote", "git@example.com:nope/missing.git"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Could not access the Git remote." in captured.err
    assert "Traceback" not in captured.err
    assert not (repo / ".git").exists()
    assert not list(paths.backups_dir.glob("*/.willy-backup.json"))


def test_setup_app_bad_remote_does_not_backup_or_init(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    profile = repo / "default" / "filament" / "ABS.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.is_orca_running", lambda: False)

    def fail_remote(*args, **kwargs):
        raise GitError("bad remote", stderr="fatal: Could not read from remote repository.")

    monkeypatch.setattr("willy.cli.validate_remote_access", fail_remote)
    runner = CliRunner()

    result = runner.invoke(app, ["setup", "--mode", "new", "--yes", "--remote", "git@example.com:nope/missing.git"])

    assert result.exit_code != 0
    assert not (repo / ".git").exists()
    assert not list(paths.backups_dir.glob("*/.willy-backup.json"))
