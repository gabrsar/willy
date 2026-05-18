from typer.testing import CliRunner

from willy.cli import HELP_TEXT, app, main
from willy.config import WillyConfig, WillyState, load_config, save_config, save_state
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


def test_main_without_stdio_launches_tray_mode(monkeypatch) -> None:
    monkeypatch.setattr("willy.cli._cli_stdio_available", lambda: False)
    monkeypatch.setattr("willy.statusbar.main", lambda start_daemon=True: 23 if start_daemon else 24)

    exit_code = main([])

    assert exit_code == 23


def test_main_no_daemon_flag_launches_tray_without_daemon(monkeypatch) -> None:
    monkeypatch.setattr("willy.statusbar.main", lambda start_daemon=True: 23 if start_daemon else 24)

    exit_code = main(["--no-daemon"])

    assert exit_code == 24


def test_status_command_runs_with_defaults(tmp_path, monkeypatch) -> None:
    paths = default_paths(tmp_path / "home")
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.is_orca_running", lambda: False)
    monkeypatch.setattr("willy.cli.pid_is_running", lambda pid: False)
    runner = CliRunner()

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Willy status" in result.output
    assert "Git repo: no" in result.output
    assert "Sensitive fields: redacted before commit" in result.output
    assert "Unsaved tracked files: 0" in result.output
    assert "Next save: daemon not running" in result.output


def test_status_shows_next_save_from_state(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    repo.mkdir(parents=True)
    run_git(repo, "init")
    save_state(
        paths,
        WillyState(
            daemon_pid=123,
            pending_save_since="2026-05-13T18:00:00-03:00",
            next_save_at="2026-05-13T18:00:03-03:00",
            pending_save_count=2,
            last_sync_at="2026-05-13T17:59:00-03:00",
            last_sync_status="synced",
        ),
    )
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.pid_is_running", lambda pid: True)
    runner = CliRunner()

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Next save: 2026-05-13T18:00:03-03:00" in result.output
    assert "2 pending batch(es)" in result.output
    assert "Last sync: synced at 2026-05-13T17:59:00-03:00" in result.output


def test_save_commits_trackable_json_only(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = default_paths(home).default_orca_user_dir
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
    assert "Sync: no remote configured" in result.output
    status = run_git(repo, "status", "--porcelain").stdout
    assert "ABS.json" not in status
    assert "ABS.info" in status


def test_save_syncs_even_when_no_changes(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = default_paths(home).default_orca_user_dir
    remote = tmp_path / "remote.git"
    remote.mkdir()
    repo.mkdir(parents=True)
    run_git(remote, "init", "--bare")
    run_git(repo, "init")
    run_git(repo, "branch", "-M", "main")
    run_git(repo, "remote", "add", "origin", str(remote))
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Willy Test")
    profile = repo / "default" / "filament" / "PETG.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "PETG"}\n', encoding="utf-8")
    run_git(repo, "add", "default/filament/PETG.json")
    run_git(repo, "commit", "-m", "initial")
    run_git(repo, "push", "-u", "origin", "main")
    monkeypatch.setattr("willy.cli.default_paths", lambda: default_paths(home))
    runner = CliRunner()

    result = runner.invoke(app, ["save", "sync only"])

    assert result.exit_code == 0
    assert "Nothing to save." in result.output
    assert "Sync: synced" in result.output


def test_save_pushes_when_remote_exists(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = default_paths(home).default_orca_user_dir
    remote = tmp_path / "remote.git"
    remote.mkdir()
    repo.mkdir(parents=True)
    run_git(remote, "init", "--bare")
    run_git(repo, "init")
    run_git(repo, "branch", "-M", "main")
    run_git(repo, "remote", "add", "origin", str(remote))
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Willy Test")
    profile = repo / "default" / "filament" / "PETG.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "PETG"}\n', encoding="utf-8")
    monkeypatch.setattr("willy.cli.default_paths", lambda: default_paths(home))
    runner = CliRunner()

    result = runner.invoke(app, ["save", "push profile"])

    assert result.exit_code == 0
    assert "Saved 1 file(s)." in result.output
    assert "Sync: synced" in result.output
    remote_log = run_git(remote, "log", "--oneline", "refs/heads/main", check=False).stdout
    assert "filament" in remote_log


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
    monkeypatch.setattr("willy.cli.start_background", lambda paths, state: 123)
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
    assert "Watcher enabled: pid 123" in result.output
    assert is_repo(repo)
    assert remote_url(repo) == str(remote)
    assert (repo / "LICENSE").exists()
    assert (repo / "README.md").exists()
    assert list(paths.backups_dir.glob("*/.willy-backup.json"))
    assert load_config(paths).remote == str(remote)
    assert load_config(paths).repo_private is False


def test_setup_saves_asset_dir_inside_repo(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    repo.mkdir(parents=True)
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.is_orca_running", lambda: False)
    monkeypatch.setattr("willy.cli.start_background", lambda paths, state: 123)
    runner = CliRunner()

    result = runner.invoke(app, ["setup", "--yes", "--no-watcher", "--asset-dir", "prints"])

    assert result.exit_code == 0
    assert "Tracked asset directories:" in result.output
    assert (repo / "prints").exists()
    assert load_config(paths).asset_dirs == (repo / "prints",)


def test_save_tracks_stl_files_inside_asset_dir(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    asset_dir = repo / "prints"
    model = asset_dir / "benchy.stl"
    asset_dir.mkdir(parents=True)
    model.write_text("solid benchy\n", encoding="utf-8")
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Willy Test")
    save_config(paths, WillyConfig(orca_user_dir=repo, repo_path=repo, asset_dirs=(asset_dir,)))
    runner = CliRunner()

    result = runner.invoke(app, ["save", "track model"])

    assert result.exit_code == 0
    assert "Saved 1 file(s)." in result.output
    status = run_git(repo, "status", "--porcelain").stdout
    assert "benchy.stl" not in status


def test_setup_existing_repo_defaults_to_yes_and_saves_config(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    profile = repo / "default" / "filament" / "ABS.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    remote = tmp_path / "remote.git"
    remote.mkdir()
    run_git(remote, "init", "--bare")
    run_git(repo, "init")
    run_git(repo, "remote", "add", "origin", str(remote))
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.is_orca_running", lambda: False)
    monkeypatch.setattr("willy.cli.start_background", lambda paths, state: 456)
    runner = CliRunner()

    result = runner.invoke(app, ["setup"], input="\n\n\n")

    assert result.exit_code == 0
    assert "Existing Git repo found:" in result.output
    assert "Use this Git repo as Willy's default? [Y/n]" in result.output
    assert "Remote access OK." in result.output
    assert "Privacy: Git can validate access" in result.output
    assert "Using existing Git repo as Willy's default." in result.output
    assert "Enable Willy watcher?" in result.output
    assert "Watcher enabled: pid 456" in result.output
    assert load_config(paths).repo_path == repo
    assert load_config(paths).remote == str(remote)
    assert load_config(paths).repo_private is False
    assert not list(paths.backups_dir.glob("*/.willy-backup.json"))


def test_setup_existing_repo_yes_flag_uses_repo_without_prompt(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    profile = repo / "default" / "filament" / "ABS.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    run_git(repo, "init")
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.is_orca_running", lambda: False)
    monkeypatch.setattr("willy.cli.start_background", lambda paths, state: 789)
    runner = CliRunner()

    result = runner.invoke(app, ["setup", "--yes"])

    assert result.exit_code == 0
    assert "Using existing Git repo as Willy's default." in result.output
    assert "Watcher enabled: pid 789" in result.output
    assert "Use this Git repo as Willy's default?" not in result.output
    assert load_config(paths).repo_path == repo
    assert not list(paths.backups_dir.glob("*/.willy-backup.json"))


def test_setup_private_repo_flag_keeps_sensitive_config(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    profile = repo / "default" / "filament" / "ABS.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    run_git(repo, "init")
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.is_orca_running", lambda: False)
    monkeypatch.setattr("willy.cli.start_background", lambda paths, state: 789)
    runner = CliRunner()

    result = runner.invoke(app, ["setup", "--yes", "--private-repo", "--no-watcher"])

    assert result.exit_code == 0
    assert "Privacy: private repo" in result.output
    assert "WARNING: this repository must not become public." in result.output
    assert load_config(paths).repo_private is True


def test_setup_existing_repo_no_cancels_without_config(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    profile = repo / "default" / "filament" / "ABS.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    run_git(repo, "init")
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.is_orca_running", lambda: False)
    runner = CliRunner()

    result = runner.invoke(app, ["setup"], input="n\n")

    assert result.exit_code != 0
    assert "Setup cancelled." in result.output
    assert not paths.config_file.exists()
    assert not list(paths.backups_dir.glob("*/.willy-backup.json"))


def test_setup_existing_repo_no_watcher_does_not_start_watcher(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    profile = repo / "default" / "filament" / "ABS.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    run_git(repo, "init")
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.is_orca_running", lambda: False)

    def fail_start(*args, **kwargs):
        raise AssertionError("watcher should not start")

    monkeypatch.setattr("willy.cli.start_background", fail_start)
    runner = CliRunner()

    result = runner.invoke(app, ["setup", "--yes", "--no-watcher"])

    assert result.exit_code == 0
    assert "Watcher not enabled. You can start it later with `willy start`." in result.output


def test_setup_existing_repo_bad_remote_does_not_save_config(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    profile = repo / "default" / "filament" / "ABS.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"name": "ABS"}\n', encoding="utf-8")
    run_git(repo, "init")
    run_git(repo, "remote", "add", "origin", str(tmp_path / "missing.git"))
    monkeypatch.setattr("willy.cli.default_paths", lambda: paths)
    monkeypatch.setattr("willy.cli.is_orca_running", lambda: False)
    runner = CliRunner()

    result = runner.invoke(app, ["setup"], input="\n")

    assert result.exit_code != 0
    assert "Validating remote access..." in result.output
    assert not paths.config_file.exists()
    assert not list(paths.backups_dir.glob("*/.willy-backup.json"))


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
