import json
from pathlib import Path

from willy.config import WillyConfig, WillyState, config_to_toml, load_config, load_state, save_config, save_state
from willy.paths import default_paths


def test_load_missing_config_returns_defaults(tmp_path: Path) -> None:
    paths = default_paths(tmp_path)

    config = load_config(paths)

    assert config.repo_path == paths.default_orca_user_dir
    assert config.orca_user_dir == paths.default_orca_user_dir


def test_config_round_trip(tmp_path: Path) -> None:
    paths = default_paths(tmp_path)
    config = WillyConfig(
        orca_user_dir=tmp_path / "orca-user",
        repo_path=tmp_path / "repo",
        remote="git@example.com:user/repo.git",
        branch="main",
    )

    save_config(paths, config)
    loaded = load_config(paths)

    assert loaded == config


def test_state_round_trip(tmp_path: Path) -> None:
    paths = default_paths(tmp_path)
    state = WillyState(
        last_commit="abc123 test",
        last_sync_at="2026-05-13T18:00:00-03:00",
        last_sync_status="ok",
        daemon_pid=123,
        pending_save_since="2026-05-13T18:00:01-03:00",
        next_save_at="2026-05-13T18:00:04-03:00",
        pending_save_count=2,
    )

    save_state(paths, state)
    loaded = load_state(paths)

    assert loaded == state


def test_load_state_accepts_utf8_bom(tmp_path: Path) -> None:
    paths = default_paths(tmp_path)
    paths.ensure_runtime_dirs()
    paths.state_file.write_bytes(b'\xef\xbb\xbf{"active_operation":"saving"}\n')

    state = load_state(paths)

    assert state.active_operation == "saving"


def test_config_round_trips_asset_dirs_and_tray_flag(tmp_path: Path) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    asset_dir = repo / "prints"
    config = WillyConfig(
        orca_user_dir=repo,
        repo_path=repo,
        asset_dirs=(asset_dir,),
        tray_enabled=True,
        show_tray_welcome=False,
    )

    save_config(paths, config)
    loaded = load_config(paths)

    assert loaded.asset_dirs == (asset_dir,)
    assert loaded.tray_enabled is True
    assert loaded.show_tray_welcome is False


def test_config_to_toml_renders_asset_dir_array(tmp_path: Path) -> None:
    home = tmp_path / "home"
    paths = default_paths(home)
    repo = paths.default_orca_user_dir
    rendered = config_to_toml(
        WillyConfig(
            orca_user_dir=repo,
            repo_path=repo,
            asset_dirs=(repo / "prints", repo / "stls"),
        )
    )

    assert "asset_dirs = [" in rendered
    assert json.dumps(str(repo / "prints")) in rendered
    assert json.dumps(str(repo / "stls")) in rendered
