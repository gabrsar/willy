from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from willy.errors import GitError

DEFAULT_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class GitResult:
    args: tuple[str, ...]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class GitStatusEntry:
    code: str
    path: str


def git_available() -> bool:
    return shutil.which("git") is not None


def run_git(
    repo: Path,
    *args: str,
    check: bool = True,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> GitResult:
    command = ("git", *args)
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitError("Git is not installed or is not on PATH.", command=command) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(
            "Git command timed out.",
            command=command,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
        ) from exc

    result = GitResult(
        args=command,
        cwd=repo,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        message = f"Git command failed: {' '.join(command)}"
        if detail:
            message = f"{message}\n{detail}"
        raise GitError(
            message,
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    return result


def git_version(repo: Path) -> str | None:
    result = run_git(repo, "--version", check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def is_repo(path: Path) -> bool:
    result = run_git(path, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def current_branch(path: Path) -> str | None:
    result = run_git(path, "branch", "--show-current", check=False)
    branch = result.stdout.strip()
    return branch or None


def remote_url(path: Path, name: str = "origin") -> str | None:
    result = run_git(path, "remote", "get-url", name, check=False)
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    return url or None


def status_porcelain(path: Path) -> list[GitStatusEntry]:
    result = run_git(path, "status", "--porcelain=v1", "--untracked-files=all", check=False)
    if result.returncode != 0:
        return []
    entries: list[GitStatusEntry] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        code = line[:2]
        file_path = line[3:] if len(line) > 3 else ""
        entries.append(GitStatusEntry(code=code, path=file_path))
    return entries


def last_commit(path: Path) -> str | None:
    result = run_git(path, "log", "-1", "--pretty=%h %s", check=False)
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return text or None


def init_repo(path: Path) -> GitResult:
    return run_git(path, "init")


def add_remote(path: Path, url: str, name: str = "origin") -> GitResult:
    existing = remote_url(path, name)
    if existing == url:
        return run_git(path, "remote", "get-url", name)
    if existing:
        return run_git(path, "remote", "set-url", name, url)
    return run_git(path, "remote", "add", name, url)


def add_paths(path: Path, paths: list[Path]) -> GitResult | None:
    if not paths:
        return None
    relative = [str(item.relative_to(path) if item.is_absolute() else item) for item in paths]
    return run_git(path, "add", "--all", "--", *relative)


def commit(path: Path, subject: str, body: str | None = None) -> GitResult:
    args = ["commit", "-m", subject]
    if body:
        args.extend(["-m", body])
    return run_git(path, *args)
