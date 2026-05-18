from __future__ import annotations

import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from willy.errors import ConfigError
from willy.paths import WillyPaths, expand_path


@dataclass(frozen=True)
class WillyConfig:
    orca_user_dir: Path
    repo_path: Path
    remote: str | None = None
    branch: str = "main"
    debounce_seconds: int = 3
    max_batch_seconds: int = 30
    protect_from_bamboo_poachers: bool = False
    launchd_enabled: bool = False
    repo_private: bool | None = None

    @classmethod
    def default(cls, paths: WillyPaths) -> WillyConfig:
        return cls(
            orca_user_dir=paths.default_orca_user_dir,
            repo_path=paths.default_orca_user_dir,
        )


@dataclass
class WillyState:
    last_commit: str | None = None
    last_sync_at: str | None = None
    last_sync_status: str | None = None
    daemon_pid: int | None = None
    active_operation: str | None = None
    pending_save_since: str | None = None
    next_save_at: str | None = None
    pending_save_count: int = 0

    @classmethod
    def empty(cls) -> WillyState:
        return cls()


def _config_from_dict(data: dict[str, Any], paths: WillyPaths) -> WillyConfig:
    default = WillyConfig.default(paths)
    home = paths.home
    return WillyConfig(
        orca_user_dir=expand_path(data.get("orca_user_dir", default.orca_user_dir), home=home),
        repo_path=expand_path(data.get("repo_path", default.repo_path), home=home),
        remote=data.get("remote", default.remote),
        branch=str(data.get("branch", default.branch)),
        debounce_seconds=int(data.get("debounce_seconds", default.debounce_seconds)),
        max_batch_seconds=int(data.get("max_batch_seconds", default.max_batch_seconds)),
        protect_from_bamboo_poachers=bool(
            data.get(
                "protect_from_bamboo_poachers",
                default.protect_from_bamboo_poachers,
            )
        ),
        launchd_enabled=bool(data.get("launchd_enabled", default.launchd_enabled)),
        repo_private=data.get("repo_private", default.repo_private),
    )


def load_config(paths: WillyPaths) -> WillyConfig:
    if not paths.config_file.exists():
        return WillyConfig.default(paths)
    try:
        data = tomllib.loads(paths.config_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Could not read config: {paths.config_file}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Config is not valid TOML: {paths.config_file}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Config must be a TOML table: {paths.config_file}")
    return _config_from_dict(data, paths)


def load_state(paths: WillyPaths) -> WillyState:
    if not paths.state_file.exists():
        return WillyState.empty()
    try:
        data = json.loads(paths.state_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Could not read state: {paths.state_file}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"State is not valid JSON: {paths.state_file}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"State must be a JSON object: {paths.state_file}")
    return WillyState(
        last_commit=data.get("last_commit"),
        last_sync_at=data.get("last_sync_at"),
        last_sync_status=data.get("last_sync_status"),
        daemon_pid=data.get("daemon_pid"),
        active_operation=data.get("active_operation"),
        pending_save_since=data.get("pending_save_since"),
        next_save_at=data.get("next_save_at"),
        pending_save_count=int(data.get("pending_save_count", 0)),
    )


def save_state(paths: WillyPaths, state: WillyState) -> None:
    paths.ensure_runtime_dirs()
    payload = json.dumps(asdict(state), indent=2, sort_keys=True)
    paths.state_file.write_text(payload + "\n", encoding="utf-8")


def config_to_toml(config: WillyConfig) -> str:
    lines: list[str] = []
    for key, value in asdict(config).items():
        if isinstance(value, Path):
            rendered = str(value)
            lines.append(f'{key} = "{rendered}"')
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif value is None:
            continue
        elif isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        else:
            lines.append(f"{key} = {value}")
    return "\n".join(lines) + "\n"


def save_config(paths: WillyPaths, config: WillyConfig) -> None:
    paths.ensure_runtime_dirs()
    paths.config_file.write_text(config_to_toml(config), encoding="utf-8")
