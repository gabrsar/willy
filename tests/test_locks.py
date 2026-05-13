from pathlib import Path

import pytest

from willy.locks import LockError, acquire_lock


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
