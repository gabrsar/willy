from __future__ import annotations

import argparse
import json
import sys
from typing import Any

REDACTED = "<redacted-by-willy>"
SENSITIVE_KEYS = {
    "print_host",
    "printhost_apikey",
    "access_code",
    "access_token",
    "api_key",
    "apikey",
    "auth_token",
    "dev_id",
    "device_id",
    "guid",
    "host",
    "hostname",
    "ip",
    "ip_address",
    "mac",
    "mac_address",
    "password",
    "printer_id",
    "secret",
    "serial",
    "serial_number",
    "sn",
    "token",
    "uuid",
}
SENSITIVE_KEY_PARTS = ("api_key", "apikey", "token", "password", "secret", "credential")


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or any(part in lowered for part in SENSITIVE_KEY_PARTS)


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: (REDACTED if is_sensitive_key(key) else redact_value(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_json_text(text: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(redact_value(data), ensure_ascii=False, indent=4) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdin", action="store_true", help="Read JSON from stdin and write redacted JSON to stdout.")
    args = parser.parse_args(argv)
    if args.stdin:
        sys.stdout.write(redact_json_text(sys.stdin.read()))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
