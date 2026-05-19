from __future__ import annotations


class WillyError(Exception):
    """Base class for expected Willy failures."""


class GitError(WillyError):
    def __init__(
        self,
        message: str,
        *,
        command: tuple[str, ...] = (),
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ConfigError(WillyError):
    """Raised when configuration cannot be loaded or saved safely."""
