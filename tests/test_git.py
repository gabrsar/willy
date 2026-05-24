from pathlib import Path

import pytest

from willy.errors import GitConflictError
from willy.git import (
    clone_remote,
    conflicted_paths,
    current_branch,
    is_repo,
    last_commit,
    pull_rebase,
    rebase_in_progress,
    remote_refs,
    remote_url,
    run_git,
    status_porcelain,
    validate_remote_access,
)


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


def test_status_porcelain_preserves_paths_with_spaces(tmp_path: Path) -> None:
    run_git(tmp_path, "init")
    profile = tmp_path / "default" / "filament" / "PETG Fast.json"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}\n", encoding="utf-8")

    entries = status_porcelain(tmp_path)

    assert entries[0].path == "default/filament/PETG Fast.json"


def test_run_git_can_return_nonzero_without_raising(tmp_path: Path) -> None:
    result = run_git(tmp_path, "rev-parse", "--is-inside-work-tree", check=False)

    assert result.returncode != 0
    assert isinstance(result.stderr, str)


def test_validate_remote_access_with_local_bare_repo(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    remote.mkdir()
    work.mkdir()
    run_git(remote, "init", "--bare")

    result = validate_remote_access(work, str(remote))

    assert result.returncode == 0


def test_remote_refs_and_clone_remote(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    clone = tmp_path / "clone"
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

    refs = remote_refs(source, str(remote))
    clone_remote(tmp_path, str(remote), clone, branch="main")

    assert "refs/heads/main" in refs
    assert (clone / "profile.json").exists()


def test_pull_rebase_raises_conflict_error_and_reports_paths(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    clone = tmp_path / "clone"
    remote.mkdir()
    source.mkdir()
    run_git(remote, "init", "--bare")
    run_git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    run_git(source, "init")
    run_git(source, "config", "user.email", "test@example.com")
    run_git(source, "config", "user.name", "Willy Test")
    (source / "profile.json").write_text('{"name": "base"}\n', encoding="utf-8")
    run_git(source, "add", "profile.json")
    run_git(source, "commit", "-m", "initial")
    run_git(source, "branch", "-M", "main")
    run_git(source, "remote", "add", "origin", str(remote))
    run_git(source, "push", "-u", "origin", "main")
    run_git(tmp_path, "clone", "--branch", "main", str(remote), str(clone))
    run_git(clone, "config", "user.email", "test@example.com")
    run_git(clone, "config", "user.name", "Willy Test")

    (source / "profile.json").write_text('{"name": "remote"}\n', encoding="utf-8")
    run_git(source, "add", "profile.json")
    run_git(source, "commit", "-m", "remote edit")
    run_git(source, "push")
    (clone / "profile.json").write_text('{"name": "local"}\n', encoding="utf-8")
    run_git(clone, "add", "profile.json")
    run_git(clone, "commit", "-m", "local edit")

    with pytest.raises(GitConflictError) as raised:
        pull_rebase(clone)

    assert "Willy hit a Git conflict" in str(raised.value)
    assert "profile.json" in str(raised.value)
    assert conflicted_paths(clone) == ["profile.json"]
    assert rebase_in_progress(clone)
