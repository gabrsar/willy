from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WillyPaths:
    home: Path
    root: Path
    config_file: Path
    state_file: Path
    logs_dir: Path
    human_log: Path
    event_log: Path
    backups_dir: Path
    locks_dir: Path
    default_orca_user_dir: Path

    def ensure_runtime_dirs(self) -> None:
        for path in (self.root, self.logs_dir, self.backups_dir, self.locks_dir):
            path.mkdir(parents=True, exist_ok=True)


def expand_path(value: str | Path, *, home: Path | None = None) -> Path:
    home = home or Path.home()
    text = str(value)
    if text == "~":
        return home
    if text.startswith("~/"):
        return home / text[2:]
    return Path(text).expanduser()


def default_paths(home: Path | None = None) -> WillyPaths:
    home = home or Path.home()
    root = home / ".willy"
    logs_dir = root / "logs"
    return WillyPaths(
        home=home,
        root=root,
        config_file=root / "config.toml",
        state_file=root / "state.json",
        logs_dir=logs_dir,
        human_log=logs_dir / "willy.log",
        event_log=logs_dir / "events.jsonl",
        backups_dir=root / "backups",
        locks_dir=root / "locks",
        default_orca_user_dir=home / "Library" / "Application Support" / "OrcaSlicer" / "user",
    )
