from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from willy.paths import WillyPaths


def setup_logging(paths: WillyPaths, *, verbose: bool = False) -> None:
    paths.ensure_runtime_dirs()
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        filename=paths.human_log,
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def write_event(paths: WillyPaths, event: str, **fields: Any) -> None:
    paths.ensure_runtime_dirs()
    payload = {
        "time": datetime.now(UTC).isoformat(),
        "event": event,
        **fields,
    }
    with paths.event_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
