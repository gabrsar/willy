from willy.orca import _windows_orca_running, is_orca_running


def test_windows_orca_running_accepts_installer_process_name() -> None:
    assert _windows_orca_running("orca-slicer.exe              1234 Console                    1     36.444 K")


def test_windows_orca_running_accepts_legacy_process_name() -> None:
    assert _windows_orca_running("OrcaSlicer.exe               5678 Console                    1     36.444 K")


def test_windows_orca_running_ignores_other_processes() -> None:
    assert not _windows_orca_running("python.exe                   9999 Console                    1      1.000 K")


def test_is_orca_running_uses_native_windows_process_api(monkeypatch) -> None:
    monkeypatch.setattr("willy.orca.sys.platform", "win32")
    monkeypatch.setattr("willy.orca._windows_orca_running_native", lambda: True)
    monkeypatch.setattr(
        "willy.orca.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("tasklist should not be called")),
    )

    assert is_orca_running() is True
