import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from willy.locks import LockError, _pid_is_running, acquire_lock


def test_lock_blocks_second_owner(tmp_path: Path) -> None:
    locks_dir = tmp_path / "locks"
    handle = acquire_lock(locks_dir, "daemon", purpose="test")
    try:
        with pytest.raises(LockError):
            acquire_lock(locks_dir, "daemon", purpose="second")
    finally:
        handle.release()


def test_lock_release_allows_reacquire(tmp_path: Path) -> None:
    locks_dir = tmp_path / "locks"
    handle = acquire_lock(locks_dir, "git", purpose="first")
    handle.release()

    second = acquire_lock(locks_dir, "git", purpose="second")
    second.release()


def test_windows_pid_check_treats_invalid_handle_as_not_running(monkeypatch) -> None:
    class FakeOpenProcess:
        restype = None

        def __call__(self, *_args):
            raise OSError("invalid handle")

    fake_ctypes = SimpleNamespace(
        windll=SimpleNamespace(kernel32=SimpleNamespace(OpenProcess=FakeOpenProcess())),
        c_void_p=object,
    )
    monkeypatch.setattr("willy.locks.sys.platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    assert _pid_is_running(123) is False
