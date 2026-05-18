from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from willy.files import classify_path
from willy.git import (
    add_paths,
    commit,
    current_branch,
    disable_redaction_filter,
    ensure_commit_identity,
    ensure_redaction_filter,
    is_repo,
    pull_rebase,
    push,
    push_set_upstream,
    remote_url,
    status_porcelain,
    upstream_branch,
)
from willy.metadata import change_type_from_status, commit_body, commit_subject, extract_metadata


@dataclass(frozen=True)
class SaveResult:
    saved: bool
    count: int
    subject: str | None = None


@dataclass(frozen=True)
class UnsavedSummary:
    count: int
    paths: list[Path]


def changed_trackable_paths(repo: Path, *, asset_dirs: tuple[Path, ...] = ()) -> tuple[str, list[Path]]:
    changed_paths: list[Path] = []
    first_event = "modified"
    for entry in status_porcelain(repo):
        event = change_type_from_status(entry.code)
        candidates = [part.strip() for part in entry.path.split(" -> ") if part.strip()]
        for candidate in candidates:
            candidate_path = Path(candidate)
            if classify_path(repo, repo / candidate_path, asset_dirs=asset_dirs).trackable:
                changed_paths.append(candidate_path)
                if len(changed_paths) == 1:
                    first_event = event
    return first_event, sorted(set(changed_paths))


def unsaved_summary(repo: Path, *, limit: int = 12, asset_dirs: tuple[Path, ...] = ()) -> UnsavedSummary:
    _event, paths = changed_trackable_paths(repo, asset_dirs=asset_dirs)
    return UnsavedSummary(count=len(paths), paths=paths[:limit])


def save_profile_changes(
    repo: Path,
    *,
    description: str,
    allow_sensitive: bool = False,
    asset_dirs: tuple[Path, ...] = (),
) -> SaveResult:
    if not is_repo(repo):
        raise ValueError(f"Not a Git repository: {repo}")

    first_event, unique_paths = changed_trackable_paths(repo, asset_dirs=asset_dirs)
    if not unique_paths:
        return SaveResult(saved=False, count=0)

    ensure_commit_identity(repo)
    stage_paths = list(unique_paths)
    attributes_path = disable_redaction_filter(repo) if allow_sensitive else ensure_redaction_filter(repo)
    if attributes_path:
        stage_paths.append(attributes_path)
    add_paths(repo, stage_paths)

    if len(unique_paths) == 1:
        commit_path = unique_paths[0]
        metadata = extract_metadata(repo, commit_path, asset_dirs=asset_dirs)
        subject = commit_subject(first_event, metadata, commit_path)
        body = commit_body(
            metadata=metadata,
            event=first_event,
            relative_path=commit_path,
            description=description,
        )
    else:
        commit_path = Path(f"{len(unique_paths)} files")
        metadata = extract_metadata(repo, unique_paths[0], asset_dirs=asset_dirs)
        subject = commit_subject("mixed", metadata, commit_path)
        body = commit_body(
            metadata=metadata,
            event="mixed",
            relative_path=commit_path,
            description=description,
            changed_paths=unique_paths,
        )

    commit(repo, subject, body)
    return SaveResult(saved=True, count=len(unique_paths), subject=subject)


def sync_repo(repo: Path) -> str:
    if not remote_url(repo):
        return "no remote configured"
    branch = current_branch(repo)
    if branch and not upstream_branch(repo):
        push_set_upstream(repo, "origin", branch)
        return "synced"
    pull_rebase(repo)
    push(repo)
    return "synced"
