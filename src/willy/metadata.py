from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from willy.files import classify_path
from willy.paths import path_to_posix

MATERIAL_PATTERN = re.compile(r"\b(PLA|PETG|ABS|ASA|TPU|TPE|PA|PC|PVA|HIPS|NYLON|TRITAN)\b", re.I)


@dataclass(frozen=True)
class ProfileMetadata:
    printer_name: str = "unknown"
    printer_family: str = "unknown"
    filament_type: str = "unknown"
    profile_type: str = "unknown"
    profile_name: str = "unknown"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _first_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def infer_filament(text: str) -> str:
    match = MATERIAL_PATTERN.search(text)
    if not match:
        return "unknown"
    return match.group(1).upper()


def extract_metadata(root: Path, relative_path: Path, *, asset_dirs: tuple[Path, ...] = ()) -> ProfileMetadata:
    path = root / relative_path
    classification = classify_path(root, path, asset_dirs=asset_dirs)
    data = _load_json(path)
    profile_name = (
        _first_string(
            data,
            "name",
            "filament_settings_id",
            "printer_settings_id",
            "print_settings_id",
        )
        or path.stem
        or "unknown"
    )

    text = " ".join(
        item
        for item in (
            profile_name,
            path.name,
            _first_string(data, "inherits", "from") or "",
        )
        if item
    )

    printer_name = "unknown"
    filament_type = "unknown"

    if classification.profile_type == "machine":
        printer_name = profile_name
    elif classification.profile_type == "filament":
        filament_type = infer_filament(text)

    return ProfileMetadata(
        printer_name=printer_name,
        filament_type=filament_type,
        profile_type=classification.profile_type,
        profile_name=profile_name,
    )


def change_type_from_status(code: str) -> str:
    if "R" in code:
        return "renamed"
    if "D" in code:
        return "deleted"
    if "A" in code or "?" in code:
        return "created"
    if "M" in code:
        return "modified"
    return "modified"


def commit_subject(change_type: str, metadata: ProfileMetadata, relative_path: Path) -> str:
    return " | ".join(
        [
            change_type,
            metadata.profile_type,
            metadata.printer_name,
            metadata.filament_type,
            path_to_posix(relative_path),
        ]
    )


def commit_body(
    *,
    metadata: ProfileMetadata,
    event: str,
    relative_path: Path,
    description: str | None = None,
    changed_paths: list[Path] | None = None,
) -> str:
    lines = []
    if description:
        lines.extend([description, ""])
    lines.extend(
        [
            f"Printer: {metadata.printer_name}",
            f"Filament: {metadata.filament_type}",
            f"Profile-Type: {metadata.profile_type}",
            f"Event: {event}",
            f"Path: {path_to_posix(relative_path)}",
        ]
    )
    if changed_paths:
        lines.append("")
        lines.append("Changed paths:")
        lines.extend(f"- {path_to_posix(path)}" for path in changed_paths)
    return "\n".join(lines)
