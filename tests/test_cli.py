from typer.testing import CliRunner

from willy.cli import HELP_TEXT, app, main
from willy.git import run_git
from willy.paths import default_paths


def test_help_text_starts_with_required_tldr() -> None:
    assert HELP_TEXT.startswith("TL;DR:\nsetup Connect OrcaSlicer profiles to Git")


def test_main_help_prints_required_tldr(capsys) -> None:
    main(["--help"])

    captured = capsys.readouterr()
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
