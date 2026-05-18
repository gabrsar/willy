from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from willy import __version__
from willy.config import WillyConfig, load_config, save_config
from willy.git import (
    add_remote,
    clone_remote,
    current_branch,
    init_repo,
    is_repo,
    remote_refs,
    remote_url,
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
    save_config(paths, replace(config, asset_dirs=(folder,)))
    write_event(paths, "statusbar_project_folder_configured", folder=str(folder), repo=str(repo))
    return f"Files and projects folder configured:\n{folder}"


def clear_project_folder(paths: WillyPaths) -> str:
    config = load_config(paths)
    save_config(paths, replace(config, asset_dirs=()))
    write_event(paths, "statusbar_project_folder_cleared")
    return "Files and projects folder cleared."


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


def show_settings_window(
    paths: WillyPaths,
    *,
    refresh_once: Callable[[], None],
    startup_enabled: Callable[[WillyPaths, WillyConfig], bool],
    set_startup_enabled: Callable[[WillyPaths, WillyConfig, bool], str],
) -> None:
    from tkinter import BOTH, BooleanVar, Canvas, Frame, Label, StringVar, Tk, messagebox, ttk

    config = load_config(paths)
    startup_was_enabled = startup_enabled(paths, config)

    window = Tk()
    window.title(f"Willy Settings - v{__version__}")
    window.geometry("980x760")
    window.minsize(860, 640)
    window.configure(bg="#101820")
    window.attributes("-topmost", True)
    window.after(700, lambda: window.attributes("-topmost", False))

    palette = {
        "bg": "#101820",
        "panel": "#f8f3ea",
        "card": "#fffdf8",
        "ink": "#17202a",
        "muted": "#65717d",
        "line": "#dfd6c8",
        "accent": "#176b5b",
        "accent_hover": "#0f574a",
    }

    style = ttk.Style(window)
    style.theme_use("clam")
    style.configure("Willy.TEntry", fieldbackground="#ffffff", bordercolor=palette["line"], padding=8)
    style.configure("Willy.TCombobox", fieldbackground="#ffffff", padding=8)
    style.configure(
        "Willy.TCheckbutton",
        background=palette["card"],
        foreground=palette["ink"],
        font=("Segoe UI", 10),
    )
    style.configure("Willy.TButton", padding=(14, 8), font=("Segoe UI", 10))
    style.configure(
        "Accent.TButton",
        padding=(16, 9),
        font=("Segoe UI", 10, "bold"),
        foreground="#ffffff",
        background=palette["accent"],
    )
    style.map("Accent.TButton", background=[("active", palette["accent_hover"])])

    shell = Frame(window, bg=palette["bg"])
    shell.pack(fill=BOTH, expand=True, padx=22, pady=22)

    header = Frame(shell, bg=palette["bg"])
    header.pack(fill="x", pady=(0, 16))
    Label(
        header,
        text="Willy Settings",
        bg=palette["bg"],
        fg="#fff8ea",
        font=("Segoe UI Variable Display", 22, "bold"),
    ).pack(anchor="w")
    Label(
        header,
        text="One place for Git sync, watched project files, startup behavior, and tray preferences.",
        bg=palette["bg"],
        fg="#cbd6dd",
        font=("Segoe UI", 10),
    ).pack(anchor="w", pady=(4, 0))

    footer = Frame(shell, bg=palette["bg"])
    footer.pack(side="bottom", fill="x", pady=(14, 0))

    scroll_shell = Frame(shell, bg=palette["panel"])
    scroll_shell.pack(side="top", fill=BOTH, expand=True)

    canvas = Canvas(scroll_shell, bg=palette["panel"], highlightthickness=0, bd=0)
    scrollbar = ttk.Scrollbar(scroll_shell, orient="vertical", command=canvas.yview)
    content = Frame(canvas, bg=palette["panel"])
    content_id = canvas.create_window((0, 0), window=content, anchor="nw")

    def configure_scroll_region(_event=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    def stretch_content(event) -> None:
        canvas.itemconfigure(content_id, width=event.width)

    content.bind("<Configure>", configure_scroll_region)
    canvas.bind("<Configure>", stretch_content)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill=BOTH, expand=True)
    scrollbar.pack(side="right", fill="y")

    def on_mousewheel(event) -> None:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind_all("<MouseWheel>", on_mousewheel)

    status_var = StringVar(value="Edit paths directly. Native folder dialogs are intentionally not used here.")
    orca_var = StringVar(value=str(config.orca_user_dir))
    repo_var = StringVar(value=str(config.repo_path))
    remote_var = StringVar(value=config.remote or remote_url(config.repo_path) or "")
    branch_var = StringVar(value=current_branch(config.repo_path) or config.branch or "main")
    asset_var = StringVar(value=str(config.asset_dirs[0]) if config.asset_dirs else "")
    debounce_var = StringVar(value=str(config.debounce_seconds))
    max_batch_var = StringVar(value=str(config.max_batch_seconds))
    privacy_var = StringVar(value="private" if config.repo_private else "public")
    initialize_var = BooleanVar(value=True)
    validate_remote_var = BooleanVar(value=False)
    protect_var = BooleanVar(value=config.protect_from_bamboo_poachers)
    startup_var = BooleanVar(value=startup_was_enabled)
    welcome_var = BooleanVar(value=config.show_tray_welcome)

    def card(title: str, subtitle: str) -> Frame:
        outer = Frame(content, bg=palette["panel"])
        outer.pack(fill="x", padx=18, pady=(0, 16))
        inner = Frame(outer, bg=palette["card"], highlightbackground=palette["line"], highlightthickness=1)
        inner.pack(fill="x")
        body = Frame(inner, bg=palette["card"])
        body.pack(fill="x", padx=20, pady=18)
        Label(body, text=title, bg=palette["card"], fg=palette["ink"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
        Label(
            body,
            text=subtitle,
            bg=palette["card"],
            fg=palette["muted"],
            font=("Segoe UI", 9),
            wraplength=860,
            justify="left",
        ).pack(anchor="w", pady=(3, 14))
        return body

    def field(parent: Frame, label: str, variable: StringVar, hint: str = "") -> ttk.Entry:
        Label(parent, text=label, bg=palette["card"], fg=palette["ink"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
        entry = ttk.Entry(parent, textvariable=variable, style="Willy.TEntry")
        entry.pack(fill="x", pady=(5, 4))
        if hint:
            Label(
                parent,
                text=hint,
                bg=palette["card"],
                fg=palette["muted"],
                font=("Segoe UI", 9),
                wraplength=860,
                justify="left",
            ).pack(anchor="w", pady=(0, 12))
        else:
            Frame(parent, height=10, bg=palette["card"]).pack(fill="x")
        return entry

    def button_row(parent: Frame, buttons: tuple[tuple[str, object], ...]) -> None:
        row = Frame(parent, bg=palette["card"])
        row.pack(fill="x", pady=(2, 12))
        for text, command in buttons:
            ttk.Button(row, text=text, command=command, style="Willy.TButton").pack(side="left", padx=(0, 8))

    paths_card = card("Paths", "These folders define where Willy reads Orca data and where the Git repository lives.")
    field(paths_card, "Orca profile directory", orca_var)
    button_row(
        paths_card,
        (
            ("Use Orca Default", lambda: orca_var.set(str(paths.default_orca_user_dir))),
            ("Use Repo Folder", lambda: orca_var.set(repo_var.get())),
        ),
    )
    field(paths_card, "Repository folder", repo_var)
    button_row(
        paths_card,
        (
            ("Use Orca Folder", lambda: repo_var.set(orca_var.get())),
            ("Use Orca Default", lambda: repo_var.set(str(paths.default_orca_user_dir))),
        ),
    )

    git_card = card(
        "Git Sync",
        "Configure origin, branch, initialization, and whether remote access should be tested before saving.",
    )
    field(git_card, "Origin remote", remote_var, "Leave empty if this machine should only keep a local repo.")
    button_row(git_card, (("Clear Remote", lambda: remote_var.set("")),))
    two_columns = Frame(git_card, bg=palette["card"])
    two_columns.pack(fill="x", pady=(0, 12))
    left = Frame(two_columns, bg=palette["card"])
    left.pack(side="left", fill="x", expand=True, padx=(0, 10))
    right = Frame(two_columns, bg=palette["card"])
    right.pack(side="left", fill="x", expand=True, padx=(10, 0))
    field(left, "Branch", branch_var)
    Label(right, text="Privacy", bg=palette["card"], fg=palette["ink"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
    ttk.Combobox(
        right,
        textvariable=privacy_var,
        values=("public", "private"),
        state="readonly",
        style="Willy.TCombobox",
    ).pack(fill="x", pady=(5, 4))
    Label(
        right,
        text="public redacts sensitive fields; private keeps them in commits.",
        bg=palette["card"],
        fg=palette["muted"],
        font=("Segoe UI", 9),
        wraplength=400,
        justify="left",
    ).pack(anchor="w", pady=(0, 12))
    ttk.Checkbutton(
        git_card,
        text="Initialize Git repo if needed",
        variable=initialize_var,
        style="Willy.TCheckbutton",
    ).pack(anchor="w", pady=(0, 6))
    ttk.Checkbutton(
        git_card,
        text="Validate remote access before saving",
        variable=validate_remote_var,
        style="Willy.TCheckbutton",
    ).pack(anchor="w")

    files_card = card(
        "Files & Projects",
        "Willy can also track .3mf and .stl files inside one project folder under the repo.",
    )
    field(files_card, "Tracked files/projects folder", asset_var)
    button_row(
        files_card,
        (
            ("Use Suggested", lambda: asset_var.set(str(Path(repo_var.get().strip().strip('"')) / "projects"))),
            ("Use Repo Folder", lambda: asset_var.set(repo_var.get())),
            ("Clear", lambda: asset_var.set("")),
        ),
    )

    behavior_card = card("Behavior", "Timing, startup, tray onboarding, and optional protection assets.")
    timing = Frame(behavior_card, bg=palette["card"])
    timing.pack(fill="x", pady=(0, 12))
    debounce_col = Frame(timing, bg=palette["card"])
    debounce_col.pack(side="left", fill="x", expand=True, padx=(0, 10))
    batch_col = Frame(timing, bg=palette["card"])
    batch_col.pack(side="left", fill="x", expand=True, padx=(10, 0))
    field(debounce_col, "Debounce seconds", debounce_var, "Wait this long after a file change before saving.")
    field(batch_col, "Max batch seconds", max_batch_var, "Maximum time to group rapid file changes.")
    ttk.Checkbutton(
        behavior_card,
        text="Start Willy tray when Windows starts",
        variable=startup_var,
        style="Willy.TCheckbutton",
    ).pack(anchor="w", pady=(0, 6))
    ttk.Checkbutton(
        behavior_card,
        text="Show tray welcome popup on startup",
        variable=welcome_var,
        style="Willy.TCheckbutton",
    ).pack(anchor="w", pady=(0, 6))
    ttk.Checkbutton(
        behavior_card,
        text="Protect from bamboo poachers",
        variable=protect_var,
        style="Willy.TCheckbutton",
    ).pack(anchor="w")

    Label(
        footer,
        textvariable=status_var,
        bg=palette["bg"],
        fg="#dce7ed",
        font=("Segoe UI", 9),
        wraplength=650,
        justify="left",
    ).pack(side="left", fill="x", expand=True)

    def parse_int(value: str, label: str) -> int | None:
        try:
            parsed = int(value.strip())
        except ValueError:
            status_var.set(f"{label} must be a whole number.")
            return None
        if parsed < 0:
            status_var.set(f"{label} cannot be negative.")
            return None
        return parsed

    def save() -> None:
        orca_text = orca_var.get().strip().strip('"')
        repo_text = repo_var.get().strip().strip('"')
        asset_text = asset_var.get().strip().strip('"')
        remote_text = remote_var.get().strip()
        if not orca_text or not repo_text:
            status_var.set("Orca profile directory and repository folder are required.")
            return
        debounce = parse_int(debounce_var.get(), "Debounce seconds")
        if debounce is None:
            return
        max_batch = parse_int(max_batch_var.get(), "Max batch seconds")
        if max_batch is None:
            return

        missing = [
            Path(value).expanduser()
            for value in (orca_text, repo_text, asset_text)
            if value and not Path(value).expanduser().exists()
        ]
        create_missing = True
        if missing:
            missing_text = "\n".join(str(path) for path in missing)
            create_missing = messagebox.askyesno(
                "Willy Settings",
                f"One or more folders do not exist yet.\n\n{missing_text}\n\nDo you want Willy to create them?",
                parent=window,
            )
            if not create_missing:
                status_var.set("Choose existing folders, clear the optional project folder, or save again to create.")
                return

        repo_path = Path(repo_text).expanduser().resolve()
        old_repo = config.repo_path.expanduser().resolve()
        old_remote = (config.remote or remote_url(config.repo_path) or "").strip()
        repo_changed = repo_path != old_repo
        remote_changed = remote_text != old_remote
        validate_remote_now = validate_remote_var.get() or bool(remote_text and (repo_changed or remote_changed))
        download_remote = False
        if remote_text and validate_remote_now:
            validation_cwd = repo_path if repo_path.exists() else repo_path.parent
            if not validation_cwd.exists():
                validation_cwd = Path.home()
            try:
                status_var.set("Checking Git remote access...")
                window.update_idletasks()
                validate_remote_access(validation_cwd, remote_text)
                refs = remote_refs(validation_cwd, remote_text)
            except Exception as exc:
                messagebox.showwarning(
                    "Willy Git Remote",
                    "Willy could not access this Git remote.\n\n"
                    f"{remote_text}\n\n"
                    f"{exc}\n\n"
                    "Check the URL, permissions, SSH key, or token, then validate again.",
                    parent=window,
                )
                status_var.set("Remote validation failed. Fix the remote or permissions before saving.")
                return

            if refs and repo_changed:
                download_remote = messagebox.askyesno(
                    "Willy Git Remote",
                    "Remote access is OK and the remote already has content.\n\n"
                    f"Branches found: {len(refs)}\n\n"
                    "Do you want Willy to download/clone that content into the selected repository folder?",
                    parent=window,
                )
            elif not refs:
                messagebox.showinfo(
                    "Willy Git Remote",
                    "Remote access is OK, but no branches were found there yet.\n"
                    "Willy will configure the remote and push when there is something to sync.",
                    parent=window,
                )

        try:
            message = configure_repository(
                paths,
                orca_user_dir=orca_text,
                repo_path=repo_text,
                remote=remote_text,
                branch=branch_var.get(),
                repo_private=privacy_var.get() == "private",
                asset_dirs=(asset_text,) if asset_text else (),
                debounce_seconds=debounce,
                max_batch_seconds=max_batch,
                protect_from_bamboo_poachers=protect_var.get(),
                tray_enabled=startup_var.get(),
                show_tray_welcome=welcome_var.get(),
                create_missing=create_missing,
                initialize_repo=initialize_var.get(),
                validate_remote=validate_remote_now,
                download_remote=download_remote,
            )
            if startup_var.get() != startup_was_enabled:
                set_startup_enabled(paths, load_config(paths), startup_var.get())
        except Exception as exc:
            message = f"Could not save settings:\n{exc}"
            write_event(
                paths,
                "statusbar_settings_save_failed",
                error=str(exc),
                traceback=traceback.format_exc(),
                platform="win32",
            )
        status_var.set(message)
        refresh_once()
        if message.startswith("Repository configured:"):
            window.after(900, window.destroy)

    ttk.Button(footer, text="Cancel", command=window.destroy, style="Willy.TButton").pack(side="right")
    ttk.Button(footer, text="Save Settings", command=save, style="Accent.TButton").pack(side="right", padx=(0, 10))

    window.lift()
    window.focus_force()
    window.mainloop()
