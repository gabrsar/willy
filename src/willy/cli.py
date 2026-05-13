from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from willy import __version__
from willy.backup import create_backup
from willy.config import load_config, load_state, save_config
from willy.errors import ConfigError, GitError, WillyError
from willy.files import classify_path
from willy.git import (
    add_paths,
    add_remote,
    commit,
    current_branch,
    git_available,
    init_repo,
    is_repo,
    last_commit,
    remote_url,
    status_porcelain,
    validate_remote_access,
)
from willy.logging import setup_logging, write_event
from willy.metadata import change_type_from_status, commit_body, commit_subject, extract_metadata
from willy.orca import is_orca_running
from willy.paths import default_paths
from willy.protection import apply_poacher_protection
from willy.ssh import (
    existing_public_keys,
    generate_ed25519_key,
    is_ssh_remote,
    public_key_text,
    setup_instructions,
)

HELP_TEXT = """TL;DR:
setup Connect OrcaSlicer profiles to Git
start Start automatic syncing
stop Stop automatic syncing
save Save changes with a description
revert Restore an older profile version
status Show sync health

Usage:
  willy setup [--mode new|existing] [--remote URL] [--protect-from-bamboo-poachers] [--dry-run]
  willy start
  willy stop
  willy save "description"
  willy status
  willy history [--printer X] [--filament X] [--profile-type X] [--since DATE]
  willy revert [--commit SHA] [--path PATH] [--dry-run]
  willy help advanced
"""


app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
    help="Local-first Git sync for OrcaSlicer profiles.",
)


def _print_help() -> None:
    typer.echo(HELP_TEXT.rstrip())


def _abort(message: str, *, exit_code: int = 1) -> None:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(exit_code)


def _format_git_error(exc: GitError) -> str:
    detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
    if "Repository not found" in detail or "Could not read from remote repository" in detail:
        return (
            "Could not access the Git remote.\n\n"
            f"{detail}\n\n"
            "Check that the repository exists and that your SSH key has access.\n"
            "For GitHub, create the empty repo first and add your public SSH key to your account."
        )
    if "Permission denied" in detail or "publickey" in detail:
        return (
            "Could not authenticate to the Git remote.\n\n"
            f"{detail}\n\n"
            "Run `willy setup --generate-ssh-key --remote <url>` or add an existing SSH key to your Git host."
        )
    return str(exc)


@app.callback()
def root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show Willy version and exit."),
    ] = False,
) -> None:
    if version:
        typer.echo(f"willy {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _print_help()
        raise typer.Exit()


@app.command()
def setup(
    protect_from_bamboo_poachers: Annotated[
        bool,
        typer.Option("--protect-from-bamboo-poachers", help="Add AGPL-3.0 protection assets for a new repo."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview setup without changing files."),
    ] = False,
    remote: Annotated[
        str | None,
        typer.Option("--remote", help="Optional Git remote URL to configure as origin."),
    ] = None,
    mode: Annotated[
        str | None,
        typer.Option("--mode", help="Setup mode: new or existing."),
    ] = None,
    generate_ssh_key: Annotated[
        bool,
        typer.Option("--generate-ssh-key", help="Generate ~/.ssh/id_ed25519 if an SSH remote has no key."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Accept safe setup defaults."),
    ] = False,
) -> None:
    """Connect OrcaSlicer profiles to Git."""
    paths = default_paths()
    setup_logging(paths)
    config = load_config(paths)

    typer.echo("Willy setup")
    typer.echo(f"Orca profile directory: {config.orca_user_dir}")
    typer.echo(f"Repo path: {config.repo_path}")

    if mode not in (None, "new", "existing"):
        _abort("--mode must be either `new` or `existing`.")

    if not git_available():
        _abort("Git is not installed. On macOS, run `xcode-select --install` and then run `willy setup` again.")

    if not config.orca_user_dir.exists():
        _abort(f"Orca profile directory does not exist: {config.orca_user_dir}")

    if is_orca_running():
        _abort("OrcaSlicer is open. Save your work, close OrcaSlicer, then run `willy setup` again.")

    if mode is None:
        if yes:
            mode = "new"
        else:
            use_existing = typer.confirm("Use an existing Git remote/repo?", default=bool(remote))
            mode = "existing" if use_existing else "new"

    if mode == "existing" and not remote:
        remote = typer.prompt("Git remote URL")

    if mode == "new" and not protect_from_bamboo_poachers and not yes:
        protect_from_bamboo_poachers = typer.confirm(
            "Do you want to protect your Orca from bamboo poachers?",
            default=False,
        )

    if remote and is_ssh_remote(remote):
        keys = existing_public_keys(paths.home)
        if not keys and generate_ssh_key and not dry_run:
            public_key = generate_ed25519_key(paths.home)
            typer.echo(setup_instructions(public_key_text(public_key)))
        elif not keys:
            typer.echo("No SSH public key found in ~/.ssh.")
            typer.echo("Run `willy setup --generate-ssh-key ...` to create one, or create your own SSH key.")

    if dry_run:
        typer.echo("Dry run: would create a timestamped backup before changing anything.")
        typer.echo("Dry run: would initialize Git in the Orca profile directory if needed.")
        if remote:
            typer.echo(f"Dry run: would configure origin remote: {remote}")
            typer.echo("Dry run: would validate remote access with Git.")
        if protect_from_bamboo_poachers:
            typer.echo("Dry run: would add AGPL-3.0 protection assets for a new repo.")
        return

    if remote:
        validate_remote_access(config.repo_path, remote)

    backup = create_backup(config.orca_user_dir, paths.backups_dir, reason="setup")
    typer.echo(f"Backup created: {backup.path}")

    if not is_repo(config.repo_path):
        init_repo(config.repo_path)
        typer.echo("Initialized Git repo.")
    else:
        typer.echo("Git repo already exists.")

    if remote:
        add_remote(config.repo_path, remote)
        typer.echo("Configured origin remote.")

    if protect_from_bamboo_poachers:
        changed = apply_poacher_protection(config.repo_path)
        if changed:
            typer.echo("Added AGPL-3.0 protection assets.")
        else:
            typer.echo("Protection assets already present.")

    save_config(
        paths,
        type(config)(
            orca_user_dir=config.orca_user_dir,
            repo_path=config.repo_path,
            remote=remote or config.remote,
            branch=config.branch,
            debounce_seconds=config.debounce_seconds,
            max_batch_seconds=config.max_batch_seconds,
            protect_from_bamboo_poachers=protect_from_bamboo_poachers or config.protect_from_bamboo_poachers,
            launchd_enabled=config.launchd_enabled,
        ),
    )
    write_event(paths, "setup", repo=str(config.repo_path), backup=str(backup.path))
    typer.echo("Setup foundation complete.")


@app.command()
def start() -> None:
    """Start automatic syncing."""
    typer.echo("start is not implemented yet.")


@app.command()
def stop() -> None:
    """Stop automatic syncing."""
    typer.echo("stop is not implemented yet.")


@app.command()
def save(description: Annotated[str, typer.Argument(help="Human description for this save.")]) -> None:
    """Save current profile changes with a description."""
    paths = default_paths()
    setup_logging(paths)
    config = load_config(paths)
    repo = config.repo_path

    if not repo.exists():
        _abort(f"Sync repo does not exist: {repo}")
    if not is_repo(repo):
        _abort(f"Sync repo is not a Git repository yet: {repo}. Run `willy setup` first.")

    entries = status_porcelain(repo)
    changed_paths: list[Path] = []
    first_event = "modified"
    for entry in entries:
        event = change_type_from_status(entry.code)
        candidates = [part.strip() for part in entry.path.split(" -> ") if part.strip()]
        for candidate in candidates:
            candidate_path = Path(candidate)
            if classify_path(repo, repo / candidate_path).trackable:
                changed_paths.append(candidate_path)
                if len(changed_paths) == 1:
                    first_event = event

    unique_paths = sorted(set(changed_paths))
    if not unique_paths:
        typer.echo("Nothing to save.")
        return

    add_paths(repo, unique_paths)

    if len(unique_paths) == 1:
        commit_path = unique_paths[0]
        metadata = extract_metadata(repo, commit_path)
        subject = commit_subject(first_event, metadata, commit_path)
        body = commit_body(
            metadata=metadata,
            event=first_event,
            relative_path=commit_path,
            description=description,
        )
    else:
        commit_path = Path(f"{len(unique_paths)} files")
        metadata = extract_metadata(repo, unique_paths[0])
        subject = commit_subject("mixed", metadata, commit_path)
        body = commit_body(
            metadata=metadata,
            event="mixed",
            relative_path=commit_path,
            description=description,
            changed_paths=unique_paths,
        )

    commit(repo, subject, body)
    write_event(paths, "manual_save", repo=str(repo), changed_paths=[str(path) for path in unique_paths])
    typer.echo(f"Saved {len(unique_paths)} file(s).")


@app.command()
def status() -> None:
    """Show sync health."""
    paths = default_paths()
    setup_logging(paths)
    try:
        config = load_config(paths)
        state = load_state(paths)
    except ConfigError as exc:
        _abort(str(exc))

    repo = config.repo_path
    repo_exists = repo.exists()
    repo_ready = repo_exists and is_repo(repo)
    branch = current_branch(repo) if repo_ready else None
    remote = remote_url(repo) if repo_ready else None
    changes = status_porcelain(repo) if repo_ready else []
    last = last_commit(repo) if repo_ready else None
    orca_running = is_orca_running()

    write_event(paths, "status", repo=str(repo), repo_ready=repo_ready, orca_running=orca_running)

    typer.echo("Willy status")
    typer.echo(f"Orca running: {'yes' if orca_running else 'no'}")
    typer.echo(f"Watched directory: {config.orca_user_dir}")
    typer.echo(f"Sync repo path: {repo}")
    typer.echo(f"Repo exists: {'yes' if repo_exists else 'no'}")
    typer.echo(f"Git repo: {'yes' if repo_ready else 'no'}")
    typer.echo(f"Git branch: {branch or 'unknown'}")
    typer.echo(f"Remote: {remote or 'none'}")
    typer.echo(f"Uncommitted changes: {len(changes)}")
    typer.echo(f"Daemon status: {'pid ' + str(state.daemon_pid) if state.daemon_pid else 'not running'}")
    typer.echo(f"Last commit: {last or state.last_commit or 'none'}")
    typer.echo(f"Last sync: {state.last_sync_status or 'none'}")


@app.command()
def history(
    printer: Annotated[str | None, typer.Option("--printer", help="Filter by printer name.")] = None,
    filament: Annotated[str | None, typer.Option("--filament", help="Filter by filament type.")] = None,
    profile_type: Annotated[str | None, typer.Option("--profile-type", help="Filter by profile type.")] = None,
    since: Annotated[str | None, typer.Option("--since", help="Show changes since this date.")] = None,
) -> None:
    """Show profile history."""
    filters = {
        "printer": printer,
        "filament": filament,
        "profile_type": profile_type,
        "since": since,
    }
    active = {key: value for key, value in filters.items() if value}
    typer.echo("history is not implemented yet.")
    if active:
        typer.echo(f"Requested filters: {active}")


@app.command()
def revert(
    commit: Annotated[str | None, typer.Option("--commit", help="Commit to restore.")] = None,
    path: Annotated[Path | None, typer.Option("--path", help="Specific profile path to restore.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview restore without changing files.")] = False,
) -> None:
    """Restore an older profile version."""
    typer.echo("revert is not implemented yet.")
    if commit:
        typer.echo(f"Commit: {commit}")
    if path:
        typer.echo(f"Path: {path}")
    if dry_run:
        typer.echo("Dry run requested.")


@app.command(name="help")
def help_command(topic: Annotated[str | None, typer.Argument(help="Optional help topic.")] = None) -> None:
    """Show beginner or advanced help."""
    if topic == "advanced":
        typer.echo(
            """Advanced:
Willy stores its own config in ~/.willy/config.toml.
Willy uses Git CLI commands only.
Use willy status first when something feels wrong.
"""
        )
        return
    _print_help()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv in (["--help"], ["-h"]):
        _print_help()
        return 0
    try:
        app(args=argv, prog_name="willy")
    except GitError as exc:
        typer.echo(f"Error: {_format_git_error(exc)}", err=True)
        return 1
    except (ConfigError, WillyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        return 1
    return 0
