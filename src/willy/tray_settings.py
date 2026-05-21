from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from willy.config import WillyConfig, load_config, save_config
from willy.git import (
    add_remote,
    clone_remote,
    init_repo,
    is_repo,
    run_git,
    validate_remote_access,
)
from willy.logging import write_event
from willy.paths import WillyPaths


def configure_project_folder(paths: WillyPaths, selected_dir: str | Path, *, create_missing: bool = True) -> str:
    config = load_config(paths)
    repo = config.repo_path.resolve()
    if not repo.exists() or not is_repo(repo):
        return "Sync repo is not ready. Run Willy setup first."

    folder = Path(selected_dir).expanduser().resolve()
    try:
        folder.relative_to(repo)
    except ValueError:
        return f"Choose a folder inside the sync repo:\n{repo}"

    if not folder.exists() and not create_missing:
        return f"Folder does not exist:\n{folder}"
    if folder.exists() and not folder.is_dir():
        return f"Path exists, but it is not a folder:\n{folder}"
    folder.mkdir(parents=True, exist_ok=True)
    access_error = validate_directory_read_write("Files and projects folder", folder)
    if access_error:
        return access_error
    save_config(paths, replace(config, asset_dirs=(folder,)))
    write_event(paths, "statusbar_project_folder_configured", folder=str(folder), repo=str(repo))
    return f"Files and projects folder configured:\n{folder}"


def clear_project_folder(paths: WillyPaths) -> str:
    config = load_config(paths)
    save_config(paths, replace(config, asset_dirs=()))
    write_event(paths, "statusbar_project_folder_cleared")
    return "Files and projects folder cleared."


def validate_directory_read_write(label: str, folder: Path) -> str | None:
    if not folder.exists():
        return f"{label} does not exist:\n{folder}"
    if not folder.is_dir():
        return f"{label} path exists, but it is not a folder:\n{folder}"

    try:
        next(folder.iterdir(), None)
    except OSError as exc:
        return f"{label} is not readable:\n{folder}\n{exc}"

    probe = folder / f".willy-write-test-{uuid4().hex}.tmp"
    try:
        with probe.open("x", encoding="utf-8") as handle:
            handle.write("willy access test\n")
    except OSError as exc:
        return f"{label} is not writable:\n{folder}\n{exc}"
    finally:
        probe.unlink(missing_ok=True)

    return None


def configure_repository(
    paths: WillyPaths,
    *,
    orca_user_dir: str | Path,
    repo_path: str | Path,
    remote: str | None,
    branch: str,
    repo_private: bool | None,
    asset_dirs: tuple[str | Path, ...] | None = None,
    debounce_seconds: int | None = None,
    max_batch_seconds: int | None = None,
    protect_from_bamboo_poachers: bool | None = None,
    tray_enabled: bool | None = None,
    show_tray_welcome: bool | None = None,
    create_missing: bool = True,
    initialize_repo: bool = True,
    validate_remote: bool = False,
    download_remote: bool = False,
) -> str:
    config = load_config(paths)
    orca_dir = Path(orca_user_dir).expanduser().resolve()
    repo = Path(repo_path).expanduser().resolve()
    branch_name = branch.strip() or "main"
    remote_url_value = remote.strip() if remote else None
    resolved_asset_dirs = tuple(Path(item).expanduser().resolve() for item in (asset_dirs or ()))

    folders_to_check = [
        ("Orca profile directory", orca_dir),
        ("Repository folder", repo),
        *(("Files and projects folder", folder) for folder in resolved_asset_dirs),
    ]
    for label, folder in folders_to_check:
        if label == "Repository folder" and download_remote and remote_url_value:
            if folder.exists() and any(folder.iterdir()) and not is_repo(folder):
                return f"Repository folder is not empty and is not a Git repo:\n{folder}"
            continue
        if not folder.exists() and not create_missing:
            return f"{label} does not exist:\n{folder}"
        if folder.exists() and not folder.is_dir():
            return f"{label} path exists, but it is not a folder:\n{folder}"
        if label == "Files and projects folder":
            try:
                folder.relative_to(repo)
            except ValueError:
                return f"Choose files and projects folders inside the sync repo:\n{repo}"

    orca_dir.mkdir(parents=True, exist_ok=True)
    if download_remote and remote_url_value and not is_repo(repo):
        clone_remote(repo.parent, remote_url_value, repo, branch=branch_name)
    else:
        repo.mkdir(parents=True, exist_ok=True)
    for folder in resolved_asset_dirs:
        folder.mkdir(parents=True, exist_ok=True)

    folders_to_validate = [
        ("Orca profile directory", orca_dir),
        ("Repository folder", repo),
        *(("Files and projects folder", folder) for folder in resolved_asset_dirs),
    ]
    for label, folder in folders_to_validate:
        access_error = validate_directory_read_write(label, folder)
        if access_error:
            return access_error

    repo_ready = is_repo(repo)
    if initialize_repo and not repo_ready:
        init_repo(repo)
        repo_ready = True

    if repo_ready:
        run_git(repo, "branch", "-M", branch_name, check=False)
        if remote_url_value:
            if validate_remote:
                validate_remote_access(repo, remote_url_value)
            add_remote(repo, remote_url_value)
    elif remote_url_value:
        return "Initialize the repository before configuring a Git remote."

    save_config(
        paths,
        replace(
            config,
            orca_user_dir=orca_dir,
            repo_path=repo,
            remote=remote_url_value,
            branch=branch_name,
            repo_private=repo_private,
            asset_dirs=resolved_asset_dirs,
            debounce_seconds=debounce_seconds if debounce_seconds is not None else config.debounce_seconds,
            max_batch_seconds=max_batch_seconds if max_batch_seconds is not None else config.max_batch_seconds,
            protect_from_bamboo_poachers=(
                protect_from_bamboo_poachers
                if protect_from_bamboo_poachers is not None
                else config.protect_from_bamboo_poachers
            ),
            tray_enabled=tray_enabled if tray_enabled is not None else config.tray_enabled,
            show_tray_welcome=show_tray_welcome if show_tray_welcome is not None else config.show_tray_welcome,
        ),
    )
    write_event(
        paths,
        "statusbar_repository_configured",
        orca_user_dir=str(orca_dir),
        repo=str(repo),
        remote=remote_url_value,
        branch=branch_name,
        initialized=repo_ready,
    )
    return f"Repository configured:\n{repo}"


def suggested_project_folder(config: WillyConfig) -> Path:
    return config.repo_path / "projects"
