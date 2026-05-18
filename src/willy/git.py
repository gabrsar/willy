from __future__ import annotations

import os
import shutil
import subprocess
import sys
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


def _resolve_git_executable() -> str | None:
    git = shutil.which("git")
    if git:
        return git
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Git" / "cmd" / "git.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Git" / "bin" / "git.exe",
        Path(os.environ.get("ProgramW6432", "")) / "Git" / "cmd" / "git.exe",
        Path(os.environ.get("LocalAppData", "")) / "Programs" / "Git" / "cmd" / "git.exe",
    ]
    for candidate in candidates:
        if str(candidate) and candidate.exists():
            return str(candidate)
    return None


@dataclass(frozen=True)
class GitSyncDelta:
    ahead: int = 0
    behind: int = 0
    needs_upstream: bool = False

    @property
    def pending(self) -> bool:
        return self.needs_upstream or self.ahead > 0 or self.behind > 0


def git_available() -> bool:
    return _resolve_git_executable() is not None


def _subprocess_creationflags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def run_git(
    repo: Path,
    *args: str,
    check: bool = True,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    env: dict[str, str] | None = None,
) -> GitResult:
    git = _resolve_git_executable()
    command = ((git or "git"), *args)
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
            creationflags=_subprocess_creationflags(),
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


def upstream_branch(path: Path) -> str | None:
    result = run_git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
    if result.returncode != 0:
        return None
    upstream = result.stdout.strip()
    return upstream or None


def remote_url(path: Path, name: str = "origin") -> str | None:
    result = run_git(path, "remote", "get-url", name, check=False)
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    return url or None


def status_porcelain(path: Path) -> list[GitStatusEntry]:
    result = run_git(path, "status", "--porcelain=v1", "--untracked-files=all", "-z", check=False)
    if result.returncode != 0:
        return []
    entries: list[GitStatusEntry] = []
    records = [record for record in result.stdout.split("\0") if record]
    index = 0
    while index < len(records):
        record = records[index]
        if len(record) < 4:
            index += 1
            continue
        code = record[:2]
        file_path = record[3:]
        entries.append(GitStatusEntry(code=code, path=file_path))
        if "R" in code or "C" in code:
            index += 2
        else:
            index += 1
    return entries


def last_commit(path: Path) -> str | None:
    result = run_git(path, "log", "-1", "--pretty=%h %s", check=False)
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return text or None


def sync_delta(path: Path) -> GitSyncDelta:
    if not remote_url(path):
        return GitSyncDelta()
    if not has_commits(path):
        return GitSyncDelta()
    if not upstream_branch(path):
        return GitSyncDelta(needs_upstream=True)
    result = run_git(path, "rev-list", "--left-right", "--count", "HEAD...@{u}", check=False)
    if result.returncode != 0:
        return GitSyncDelta()
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return GitSyncDelta()
    try:
        ahead, behind = int(parts[0]), int(parts[1])
    except ValueError:
        return GitSyncDelta()
    return GitSyncDelta(ahead=ahead, behind=behind)


def init_repo(path: Path) -> GitResult:
    return run_git(path, "init")


def add_remote(path: Path, url: str, name: str = "origin") -> GitResult:
    existing = remote_url(path, name)
    if existing == url:
        return run_git(path, "remote", "get-url", name)
    if existing:
        return run_git(path, "remote", "set-url", name, url)
    return run_git(path, "remote", "add", name, url)


def validate_remote_access(path: Path, url: str) -> GitResult:
    return run_git(path, "ls-remote", url)


def remote_refs(path: Path, url: str) -> list[str]:
    result = run_git(path, "ls-remote", "--heads", url)
    refs = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            refs.append(parts[1])
    return refs


def clone_remote(parent: Path, url: str, destination: Path, *, branch: str | None = None) -> GitResult:
    parent.mkdir(parents=True, exist_ok=True)
    args = ["clone"]
    if branch:
        args.extend(["--branch", branch])
    args.extend([url, str(destination)])
    return run_git(parent, *args)


def add_paths(path: Path, paths: list[Path]) -> GitResult | None:
    if not paths:
        return None
    relative = [str(item.relative_to(path) if item.is_absolute() else item) for item in paths]
    return run_git(path, "add", "--all", "--", *relative)


def ensure_redaction_filter(path: Path) -> Path:
    attributes = path / ".gitattributes"
    line = "*.json filter=willy-redact"
    existing = attributes.read_text(encoding="utf-8").splitlines() if attributes.exists() else []
    if line not in existing:
        existing.append(line)
        attributes.write_text("\n".join(existing) + "\n", encoding="utf-8")
    config_set(path, "filter.willy-redact.clean", f'"{sys.executable}" -m willy.redact --stdin')
    config_set(path, "filter.willy-redact.smudge", "cat")
    config_set(path, "filter.willy-redact.required", "true")
    return attributes


def disable_redaction_filter(path: Path) -> Path | None:
    attributes = path / ".gitattributes"
    if not attributes.exists():
        return None
    lines = [
        line for line in attributes.read_text(encoding="utf-8").splitlines() if line != "*.json filter=willy-redact"
    ]
    attributes.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
    run_git(path, "config", "--unset-all", "filter.willy-redact.clean", check=False)
    run_git(path, "config", "--unset-all", "filter.willy-redact.smudge", check=False)
    run_git(path, "config", "--unset-all", "filter.willy-redact.required", check=False)
    return attributes


def commit(path: Path, subject: str, body: str | None = None) -> GitResult:
    args = ["commit", "-m", subject]
    if body:
        args.extend(["-m", body])
    return run_git(path, *args)


def has_commits(path: Path) -> bool:
    result = run_git(path, "rev-parse", "--verify", "HEAD", check=False)
    return result.returncode == 0


def config_get(path: Path, key: str) -> str | None:
    result = run_git(path, "config", "--get", key, check=False)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def config_get_local(path: Path, key: str) -> str | None:
    result = run_git(path, "config", "--local", "--get", key, check=False)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def config_set(path: Path, key: str, value: str) -> GitResult:
    return run_git(path, "config", key, value)


def ensure_commit_identity(path: Path) -> None:
    if not config_get_local(path, "user.name"):
        config_set(path, "user.name", "Willy")
    if not config_get_local(path, "user.email"):
        config_set(path, "user.email", "willy@local")


def pull_rebase(path: Path) -> GitResult:
    return run_git(path, "pull", "--rebase")


def push(path: Path) -> GitResult:
    return run_git(path, "push")


def push_set_upstream(path: Path, remote: str, branch: str) -> GitResult:
    return run_git(path, "push", "-u", remote, branch)
