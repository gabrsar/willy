from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

IGNORED_NAMES = {
    ".DS_Store",
    "Thumbs.db",
}

IGNORED_SUFFIXES = {
    ".tmp",
    ".temp",
    ".lock",
    ".swp",
    ".swo",
    ".part",
    ".download",
}

IGNORED_PARTS = {
    ".git",
    "__pycache__",
    "cache",
    "log",
    "logs",
}


@dataclass(frozen=True)
class FileClassification:
    relative_path: Path
    trackable: bool
    profile_type: str
    reason: str


def _profile_type(relative_path: Path) -> str:
    parts = relative_path.parts
    if len(parts) >= 2 and parts[0] == "default":
        if parts[1] == "filament":
            return "filament"
        if parts[1] == "machine":
            return "machine"
        if parts[1] == "process":
            return "process"
    if len(parts) >= 2 and parts[0].isdigit():
        if parts[1] == "filament":
            return "filament"
        if parts[1] == "machine":
            return "machine"
        if parts[1] == "process":
            return "process"
    return "config"


def relative_to_root(root: Path, path: Path) -> Path:
    return path.resolve().relative_to(root.resolve())


def _is_within(relative_path: Path, candidate_dir: Path) -> bool:
    if not candidate_dir.parts:
        return False
    try:
        relative_path.relative_to(candidate_dir)
    except ValueError:
        return False
    return True


def classify_path(root: Path, path: Path, *, asset_dirs: tuple[Path, ...] = ()) -> FileClassification:
    try:
        relative_path = relative_to_root(root, path)
    except ValueError:
        return FileClassification(Path(str(path)), False, "unknown", "outside watched directory")

    if any(part in IGNORED_PARTS for part in relative_path.parts):
        return FileClassification(relative_path, False, "unknown", "ignored directory")

    if path.name in IGNORED_NAMES:
        return FileClassification(relative_path, False, "unknown", "ignored filename")

    if path.suffix.lower() in IGNORED_SUFFIXES:
        return FileClassification(relative_path, False, "unknown", "ignored suffix")

    if path.name.startswith("."):
        return FileClassification(relative_path, False, "unknown", "hidden file")

    profile_type = _profile_type(relative_path)

    if path.suffix.lower() == ".json":
        return FileClassification(relative_path, True, profile_type, "json profile/config")

    if path.suffix.lower() in {".3mf", ".stl"}:
        normalized_asset_dirs: list[Path] = []
        for asset_dir in asset_dirs:
            try:
                normalized_asset_dirs.append(relative_to_root(root, asset_dir))
            except ValueError:
                continue
        if any(_is_within(relative_path, asset_dir) for asset_dir in normalized_asset_dirs):
            return FileClassification(relative_path, True, "asset", "tracked model asset")
        return FileClassification(relative_path, False, "asset", "model asset outside configured asset directories")

    if path.suffix.lower() == ".info":
        return FileClassification(relative_path, False, profile_type, "sidecar metadata not tracked in v1")

    return FileClassification(relative_path, False, profile_type, "unsupported file type")


def trackable_paths(root: Path, *, asset_dirs: tuple[Path, ...] = ()) -> list[Path]:
    if not root.exists():
        return []
    paths: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and classify_path(root, path, asset_dirs=asset_dirs).trackable:
            paths.append(path)
    return sorted(paths)
