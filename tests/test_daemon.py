from pathlib import Path

from willy.config import WillyConfig, WillyState, load_state
from willy.daemon import ChangeCollector, pid_is_running, run_daemon
from willy.paths import default_paths


def test_change_collector_marks_trackable_json(tmp_path: Path) -> None:
    collector = ChangeCollector(tmp_path)
    profile = tmp_path / "default" / "process" / "Fast.json"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}\n", encoding="utf-8")

    event = type("Event", (), {"is_directory": False, "src_path": str(profile)})()
    collector.on_any_event(event)

    assert collector.consume()
    assert not collector.consume()


def test_change_collector_ignores_info_sidecar(tmp_path: Path) -> None:
    collector = ChangeCollector(tmp_path)
    sidecar = tmp_path / "default" / "process" / "Fast.info"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("setting_id = PPUS\n", encoding="utf-8")

    event = type("Event", (), {"is_directory": False, "src_path": str(sidecar)})()
    collector.on_any_event(event)

    assert not collector.consume()


def test_run_daemon_once_idle_records_stopped_state(tmp_path: Path) -> None:
    paths = default_paths(tmp_path / "home")
    repo = tmp_path / "repo"
    repo.mkdir()
    config = WillyConfig(orca_user_dir=repo, repo_path=repo)

    run_daemon(
        paths,
        config,
        state=WillyState.empty(),
        is_orca_running_func=lambda: False,
        poll_seconds=0.01,
        once=True,
    )

    assert load_state(paths).daemon_pid is None


def test_pid_is_running_false_for_missing_pid() -> None:
    assert not pid_is_running(999_999_999)
