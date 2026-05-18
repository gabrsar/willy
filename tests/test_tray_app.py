from willy.paths import default_paths
from willy.tray_app import _append_tray_log, main


def test_append_tray_log_writes_file(tmp_path, monkeypatch) -> None:
    paths = default_paths(tmp_path / "home")
    monkeypatch.setattr("willy.tray_app.default_paths", lambda: paths)

    _append_tray_log("hello tray")

    contents = (paths.logs_dir / "tray.log").read_text(encoding="utf-8")
    assert "hello tray" in contents


def test_main_routes_unified_entrypoint(tmp_path, monkeypatch) -> None:
    paths = default_paths(tmp_path / "home")
    monkeypatch.setattr("willy.tray_app.default_paths", lambda: paths)
    monkeypatch.setattr("willy.tray_app._bootstrap_logging", lambda argv: None)
    called: list[list[str]] = []
    monkeypatch.setattr("willy.tray_app.willy_main", lambda argv: called.append(list(argv)) or 5)

    exit_code = main(["--no-daemon"])

    assert exit_code == 5
    assert called == [["--no-daemon"]]
