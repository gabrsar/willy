from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from willy import __version__
from willy.backup import create_backup
from willy.config import load_config, load_state, save_config, save_state
from willy.daemon import pid_is_running, run_daemon, start_background, stop_background
from willy.errors import ConfigError, GitError, WillyError
from willy.git import (
    add_remote,
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
from willy.operations import save_profile_changes, sync_repo, unsaved_summary
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
  willy setup [--mode new|existing] [--remote URL] [--asset-dir PATH] [--protect-from-bamboo-poachers] [--dry-run]
  willy daemon
  willy statusbar
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


def _stream_is_tty(stream) -> bool:
    return bool(stream and hasattr(stream, "isatty") and stream.isatty())


def _cli_stdio_available() -> bool:
    return _stream_is_tty(sys.stdin) and _stream_is_tty(sys.stdout)


def _should_launch_tray(argv: list[str]) -> bool:
    if any(
        arg in {"setup", "start", "stop", "save", "status", "history", "revert", "help", "daemon", "statusbar"}
        for arg in argv
    ):
        return False
    if argv == ["--help"] or argv == ["-h"] or argv == ["--version"]:
        return False
    if argv == ["--no-daemon"]:
        return True
    return not argv and not _cli_stdio_available()


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


def _format_sync_line(state) -> str:
    if not state.last_sync_status:
        return "none"
    if not state.last_sync_at:
        return state.last_sync_status
    return f"{state.last_sync_status} at {state.last_sync_at}"


def _format_next_save(state, *, daemon_running: bool, unsaved_count: int) -> str:
    if state.next_save_at:
        try:
            next_save = datetime.fromisoformat(state.next_save_at)
            seconds = max(0, int((next_save - datetime.now(next_save.tzinfo)).total_seconds()))
            return f"{state.next_save_at} (~{seconds}s, {state.pending_save_count} pending batch(es))"
        except ValueError:
            return state.next_save_at
    if not daemon_running:
        return "daemon not running"
    if unsaved_count:
        return "waiting for new file event or Orca close"
    return "no pending save"


WATCHER_EXPLANATION = (
    "Enable Willy watcher? It runs in the background, watches Orca profile changes, "
    "auto-saves after changes settle, and syncs again when Orca closes."
)

PRIVACY_EXPLANATION = (
    "Is this repository private? Willy only commits sensitive printer connection fields "
    "(like print_host and printhost_apikey) when the repo is private. Public or unknown "
    "repos get those fields redacted before Git stores them."
)

PRIVATE_REPO_WARNING = (
    "WARNING: this repository must not become public. It may contain printer IPs, "
    "device IDs, API keys, tokens, or other sensitive OrcaSlicer printer data."
)


def _wants_watcher(*, yes: bool, no_watcher: bool) -> bool:
    if no_watcher:
        return False
    if yes:
        return True
    return typer.confirm(WATCHER_EXPLANATION, default=True)


def _enable_watcher(paths, *, yes: bool, no_watcher: bool, dry_run: bool) -> None:
    if not _wants_watcher(yes=yes, no_watcher=no_watcher):
        typer.echo("Watcher not enabled. You can start it later with `willy start`.")
        return
    if dry_run:
        typer.echo("Dry run: would enable the Willy watcher.")
        return
    pid = start_background(paths, load_state(paths))
    write_event(paths, "setup_watcher_enabled", pid=pid)
    typer.echo(f"Watcher enabled: pid {pid}")


def _resolve_asset_dirs(repo_path: Path, asset_dirs: list[Path] | None) -> tuple[Path, ...]:
    resolved: list[Path] = []
    repo_root = repo_path.resolve()
    for asset_dir in asset_dirs or []:
        candidate = asset_dir if asset_dir.is_absolute() else repo_path / asset_dir
        candidate = candidate.resolve()
        try:
            candidate.relative_to(repo_root)
        except ValueError:
            _abort(f"Asset directory must be inside the sync repo: {candidate}\nSync repo path: {repo_path}")
        resolved.append(candidate)
    return tuple(dict.fromkeys(resolved))


def _resolve_repo_private(
    remote: str | None,
    *,
    yes: bool,
    private_repo: bool,
    public_repo: bool,
) -> bool:
    if private_repo and public_repo:
        _abort("Use either --private-repo or --public-repo, not both.")
    if private_repo:
        typer.echo("Privacy: private repo; sensitive printer fields will be kept.")
        typer.echo(PRIVATE_REPO_WARNING)
        return True
    if public_repo:
        typer.echo("Privacy: public repo; sensitive printer fields will be redacted before commit.")
        return False

    if remote:
        typer.echo("Privacy: Git can validate access, but it cannot prove whether this repo is public or private.")
    else:
        typer.echo("Privacy: no remote configured; defaulting to the safer public/unknown policy.")
    if yes:
        typer.echo("Privacy: defaulting to redaction. Use --private-repo only if this repo is private.")
        return False
    resolved_private = typer.confirm(PRIVACY_EXPLANATION, default=False)
    if resolved_private:
        typer.echo(PRIVATE_REPO_WARNING)
    return resolved_private


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
    no_watcher: Annotated[
        bool,
        typer.Option("--no-watcher", help="Do not start the background watcher after setup."),
    ] = False,
    private_repo: Annotated[
        bool,
        typer.Option("--private-repo", help="Keep sensitive printer connection fields in Git commits."),
    ] = False,
    public_repo: Annotated[
        bool,
        typer.Option("--public-repo", help="Redact sensitive printer connection fields before Git commits."),
    ] = False,
    asset_dir: Annotated[
        list[Path] | None,
        typer.Option(
            "--asset-dir",
            help="Track .3mf and .stl files under this directory inside the sync repo. Repeat to add more folders.",
        ),
    ] = None,
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
        _abort(
            "Git is not installed. Install Git for your platform, confirm `git` works in a new terminal, "
            "then run `willy setup` again."
        )

    if not config.orca_user_dir.exists():
        _abort(f"Orca profile directory does not exist: {config.orca_user_dir}")

    if is_orca_running():
        _abort("OrcaSlicer is open. Save your work, close OrcaSlicer, then run `willy setup` again.")

    resolved_asset_dirs = _resolve_asset_dirs(config.repo_path, asset_dir)
    if resolved_asset_dirs:
        typer.echo("Tracked asset directories:")
        for directory in resolved_asset_dirs:
            typer.echo(f"  {directory}")

    existing_repo = is_repo(config.repo_path)
    detected_remote = remote_url(config.repo_path) if existing_repo else None
    remote_was_provided = remote is not None

    if existing_repo:
        typer.echo(f"Existing Git repo found: {config.repo_path}")
        if detected_remote:
            typer.echo(f"Existing origin remote: {detected_remote}")
        if remote is None:
            remote = detected_remote

        use_existing_repo = yes
        if not yes and mode is None:
            use_existing_repo = typer.confirm("Use this Git repo as Willy's default?", default=True)

        if use_existing_repo or mode in ("existing", "new"):
            if remote and not dry_run:
                typer.echo("Validating remote access...")
                validate_remote_access(config.repo_path, remote)
                if remote_was_provided:
                    add_remote(config.repo_path, remote)
                    typer.echo("Configured origin remote.")
                else:
                    typer.echo("Remote access OK.")
            elif remote and dry_run:
                typer.echo(f"Dry run: would configure origin remote: {remote}")
                typer.echo("Dry run: would validate remote access with Git.")

            repo_private = _resolve_repo_private(
                remote,
                yes=yes,
                private_repo=private_repo,
                public_repo=public_repo,
            )

            if protect_from_bamboo_poachers and not dry_run:
                changed = apply_poacher_protection(config.repo_path)
                if changed:
                    typer.echo("Added AGPL-3.0 protection assets.")
                else:
                    typer.echo("Protection assets already present.")
            elif protect_from_bamboo_poachers and dry_run:
                typer.echo("Dry run: would add AGPL-3.0 protection assets for the existing repo.")

            if dry_run:
                typer.echo("Dry run: would save this Git repo as Willy's default.")
                _enable_watcher(paths, yes=yes, no_watcher=no_watcher, dry_run=True)
                return

            for directory in resolved_asset_dirs:
                directory.mkdir(parents=True, exist_ok=True)
            save_config(
                paths,
                replace(
                    config,
                    repo_path=config.repo_path,
                    remote=remote or config.remote,
                    protect_from_bamboo_poachers=protect_from_bamboo_poachers or config.protect_from_bamboo_poachers,
                    repo_private=repo_private,
                    asset_dirs=resolved_asset_dirs or config.asset_dirs,
                ),
            )
            write_event(paths, "setup_existing_repo", repo=str(config.repo_path), remote=remote)
            typer.echo("Using existing Git repo as Willy's default.")
            _enable_watcher(paths, yes=yes, no_watcher=no_watcher, dry_run=False)
            return

        _abort("Setup cancelled. Willy did not change your config.")

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
        for directory in resolved_asset_dirs:
            typer.echo(f"Dry run: would create tracked asset directory: {directory}")
        _enable_watcher(paths, yes=yes, no_watcher=no_watcher, dry_run=True)
        return

    if remote:
        validate_remote_access(config.repo_path, remote)

    repo_private = _resolve_repo_private(
        remote,
        yes=yes,
        private_repo=private_repo,
        public_repo=public_repo,
    )

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

    for directory in resolved_asset_dirs:
        directory.mkdir(parents=True, exist_ok=True)

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
            repo_private=repo_private,
            asset_dirs=resolved_asset_dirs,
            tray_enabled=config.tray_enabled,
            show_tray_welcome=config.show_tray_welcome,
        ),
    )
    write_event(paths, "setup", repo=str(config.repo_path), backup=str(backup.path))
    typer.echo("Setup foundation complete.")
    _enable_watcher(paths, yes=yes, no_watcher=no_watcher, dry_run=False)


@app.command()
def start() -> None:
    """Start automatic syncing."""
    paths = default_paths()
    setup_logging(paths)
    state = load_state(paths)
    pid = start_background(paths, state)
    write_event(paths, "start", pid=pid)
    typer.echo(f"Willy daemon running: pid {pid}")


@app.command()
def stop() -> None:
    """Stop automatic syncing."""
    paths = default_paths()
    setup_logging(paths)
    state = load_state(paths)
    stopped = stop_background(paths, state)
    write_event(paths, "stop", stopped=stopped)
    if stopped:
        typer.echo("Willy daemon stopped.")
    else:
        typer.echo("Willy daemon was not running.")


@app.command()
def daemon(
    once: Annotated[
        bool,
        typer.Option("--once", help="Run one idle/close cycle then exit. Useful for tests and debugging."),
    ] = False,
    poll_seconds: Annotated[
        float,
        typer.Option("--poll-seconds", help="Seconds between Orca process checks."),
    ] = 2.0,
) -> None:
    """Run the background watcher."""
    paths = default_paths()
    setup_logging(paths)
    config = load_config(paths)
    state = load_state(paths)
    run_daemon(
        paths,
        config,
        state=state,
        is_orca_running_func=is_orca_running,
        poll_seconds=poll_seconds,
        once=once,
    )


@app.command()
def statusbar(
    poll_seconds: Annotated[
        float,
        typer.Option("--poll-seconds", help="Seconds between status bar refreshes."),
    ] = 2.0,
    no_daemon: Annotated[
        bool,
        typer.Option("--no-daemon", help="Open the tray/status bar without starting the embedded daemon."),
    ] = False,
) -> None:
    """Run the tray/status bar icon."""
    from willy.statusbar import run_statusbar

    try:
        run_statusbar(poll_seconds=poll_seconds, start_daemon=not no_daemon)
    except RuntimeError as exc:
        _abort(str(exc))


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

    result = save_profile_changes(
        repo,
        description=description,
        allow_sensitive=bool(config.repo_private),
        asset_dirs=config.asset_dirs,
    )
    if not result.saved:
        typer.echo("Nothing to save.")
    else:
        write_event(paths, "manual_save", repo=str(repo), count=result.count, subject=result.subject)
        typer.echo(f"Saved {result.count} file(s).")

    sync_status = sync_repo(repo)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    state = load_state(paths)
    save_state(paths, replace(state, last_sync_at=now, last_sync_status=sync_status))
    write_event(paths, "manual_save_sync", repo=str(repo), sync_status=sync_status)
    typer.echo(f"Sync: {sync_status}")


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
    unsaved = unsaved_summary(repo, asset_dirs=config.asset_dirs) if repo_ready else None
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
    if config.asset_dirs:
        typer.echo("Tracked asset directories:")
        for directory in config.asset_dirs:
            typer.echo(f"  {directory}")
    typer.echo(
        "Sensitive fields: " + ("kept in commits (private repo)" if config.repo_private else "redacted before commit")
    )
    typer.echo(f"Uncommitted changes: {len(changes)}")
    typer.echo(f"Unsaved tracked files: {unsaved.count if unsaved else 0}")
    if unsaved and unsaved.paths:
        typer.echo("Unsaved tracked paths:")
        for path in unsaved.paths:
            typer.echo(f"  {path}")
    daemon_running = pid_is_running(state.daemon_pid)
    daemon_status = f"pid {state.daemon_pid}" if daemon_running else "not running"
    next_save = _format_next_save(state, daemon_running=daemon_running, unsaved_count=unsaved.count if unsaved else 0)
    typer.echo(f"Daemon status: {daemon_status}")
    typer.echo(f"Next save: {next_save}")
    typer.echo(f"Last commit: {last or state.last_commit or 'none'}")
    typer.echo(f"Last sync: {_format_sync_line(state)}")


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
    if argv == ["--daemon"]:
        daemon()
        return 0
    if _should_launch_tray(argv):
        from willy.statusbar import main as statusbar_main

        return statusbar_main(start_daemon="--no-daemon" not in argv)
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
