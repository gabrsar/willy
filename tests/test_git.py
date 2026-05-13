from pathlib import Path

from willy.git import current_branch, is_repo, last_commit, remote_url, run_git, status_porcelain


def test_git_repo_helpers(tmp_path: Path) -> None:
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "user.email", "test@example.com")
    run_git(tmp_path, "config", "user.name", "Willy Test")
    (tmp_path / "profile.json").write_text('{"name": "Profile"}\n', encoding="utf-8")
    run_git(tmp_path, "add", "profile.json")
    run_git(tmp_path, "commit", "-m", "initial")

    assert is_repo(tmp_path)
    assert current_branch(tmp_path) in {"main", "master"}
    assert remote_url(tmp_path) is None
    assert last_commit(tmp_path) is not None


def test_status_porcelain_reports_changes(tmp_path: Path) -> None:
    run_git(tmp_path, "init")
    (tmp_path / "profile.json").write_text("{}\n", encoding="utf-8")

    entries = status_porcelain(tmp_path)

    assert len(entries) == 1
    assert entries[0].code == "??"
    assert entries[0].path == "profile.json"


def test_run_git_can_return_nonzero_without_raising(tmp_path: Path) -> None:
    result = run_git(tmp_path, "rev-parse", "--is-inside-work-tree", check=False)

    assert result.returncode != 0
    assert isinstance(result.stderr, str)
