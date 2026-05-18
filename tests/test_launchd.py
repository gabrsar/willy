from willy.launchd import LABEL, launch_agent_path, launchd_plist
from willy.paths import default_paths


def test_launchd_plist_runs_willy_daemon(tmp_path) -> None:
    paths = default_paths(tmp_path)

    plist = launchd_plist(paths, executable="/tmp/python")

    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == ["/tmp/python", "-m", "willy", "daemon"]
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True
    assert str(paths.logs_dir) in plist["StandardOutPath"]


def test_launch_agent_path_uses_user_launch_agents(tmp_path) -> None:
    paths = default_paths(tmp_path)

    assert launch_agent_path(paths) == tmp_path / "Library" / "LaunchAgents" / "com.willy.daemon.plist"
