from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Backup:
    path: Path
    source: Path
    reason: str
    created_at: str


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def create_backup(source: Path, backups_dir: Path, *, reason: str) -> Backup:
    if not source.exists():
        raise FileNotFoundError(f"Cannot back up missing path: {source}")
    backups_dir.mkdir(parents=True, exist_ok=True)
    destination = backups_dir / f"{timestamp()}-{reason}"
    if destination.exists():
        raise FileExistsError(f"Backup already exists: {destination}")

    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        destination.mkdir(parents=True)
        shutil.copy2(source, destination / source.name)

    backup = Backup(
        path=destination,
        source=source,
        reason=reason,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    manifest = {
        "path": str(backup.path),
        "source": str(backup.source),
        "reason": backup.reason,
        "created_at": backup.created_at,
    }
    (destination / ".willy-backup.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return backup


def list_backups(backups_dir: Path) -> list[Backup]:
    if not backups_dir.exists():
        return []
    backups: list[Backup] = []
    for manifest_path in sorted(backups_dir.glob("*/.willy-backup.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        backups.append(
            Backup(
                path=Path(data["path"]),
                source=Path(data["source"]),
                reason=str(data["reason"]),
                created_at=str(data["created_at"]),
            )
        )
    return backups
