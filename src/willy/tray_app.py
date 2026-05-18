from __future__ import annotations

import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from willy.cli import main as willy_main
from willy.paths import default_paths


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _tray_log_path(name: str) -> Path:
    paths = default_paths()
    paths.ensure_runtime_dirs()
    return paths.logs_dir / name


def _append_tray_log(message: str) -> None:
    log_path = _tray_log_path("tray.log")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{_timestamp()} {message}\n")


def _redirect_stream(name: str, stream: TextIO) -> TextIO:
    redirected = _tray_log_path(name).open("a", encoding="utf-8")
    redirected.write(f"{_timestamp()} redirected stream begin\n")
    redirected.flush()
    return redirected


def _install_stream_redirects() -> None:
    sys.stdout = _redirect_stream("tray.out.log", sys.stdout)
    sys.stderr = _redirect_stream("tray.err.log", sys.stderr)


def _log_exception(exc_type, exc, tb) -> None:
    rendered = "".join(traceback.format_exception(exc_type, exc, tb)).rstrip()
    _append_tray_log(f"uncaught exception:\n{rendered}")


def _bootstrap_logging(argv: list[str]) -> None:
    _install_stream_redirects()
    sys.excepthook = _log_exception
    _append_tray_log(f"bootstrap argv={argv!r} frozen={getattr(sys, 'frozen', False)} executable={sys.executable!r}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _bootstrap_logging(argv)
    try:
        _append_tray_log("launching unified willy entrypoint")
        exit_code = willy_main(argv)
        _append_tray_log(f"willy exited with code={exit_code}")
        return exit_code
    except Exception:
        _append_tray_log(f"fatal exception in main:\n{traceback.format_exc().rstrip()}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
