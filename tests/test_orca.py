from willy.orca import _windows_orca_running


def test_windows_orca_running_accepts_installer_process_name() -> None:
    assert _windows_orca_running("orca-slicer.exe              1234 Console                    1     36.444 K")


def test_windows_orca_running_accepts_legacy_process_name() -> None:
    assert _windows_orca_running("OrcaSlicer.exe               5678 Console                    1     36.444 K")


def test_windows_orca_running_ignores_other_processes() -> None:
    assert not _windows_orca_running("python.exe                   9999 Console                    1      1.000 K")
