from willy.paths import default_paths
from willy.windows_startup import (
    disable_windows_startup,
    enable_windows_startup,
    startup_script_path,
    windows_startup_enabled,
)


def test_enable_and_disable_windows_startup(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    appdata = home / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    paths = default_paths(home)

    script_path = enable_windows_startup(paths, executable="C:/Python311/python.exe")

    assert script_path == startup_script_path(paths)
    assert script_path.exists()
    contents = script_path.read_text(encoding="utf-8")
    assert "-m willy statusbar" in contents
    assert "shell.Run" in contents
    assert "pythonw.exe" in contents or "python.exe" in contents
    assert windows_startup_enabled(paths) is True

    disable_windows_startup(paths)

    assert windows_startup_enabled(paths) is False
