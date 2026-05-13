from __future__ import annotations

import re
import subprocess
from pathlib import Path

from willy.errors import WillyError

SSH_REMOTE_PATTERN = re.compile(r"^(git@[^:]+:.+|ssh://.+)$")


def is_ssh_remote(remote: str) -> bool:
    return bool(SSH_REMOTE_PATTERN.match(remote))


def public_key_candidates(home: Path) -> list[Path]:
    ssh_dir = home / ".ssh"
    return [
        ssh_dir / "id_ed25519.pub",
        ssh_dir / "id_ecdsa.pub",
        ssh_dir / "id_rsa.pub",
    ]


def existing_public_keys(home: Path) -> list[Path]:
    return [path for path in public_key_candidates(home) if path.exists()]


def default_private_key(home: Path) -> Path:
    return home / ".ssh" / "id_ed25519"


def generate_ed25519_key(home: Path, *, comment: str = "willy") -> Path:
    private_key = default_private_key(home)
    public_key = (
        private_key.with_suffix(private_key.suffix + ".pub") if private_key.suffix else Path(str(private_key) + ".pub")
    )
    if public_key.exists():
        return public_key
    private_key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    result = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-C", comment, "-f", str(private_key), "-N", ""],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise WillyError(f"Could not generate SSH key with ssh-keygen. {detail}")
    return public_key


def public_key_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def setup_instructions(public_key: str) -> str:
    return (
        "Add this SSH public key to your Git host, then run setup again if remote validation failed:\n\n"
        f"{public_key}\n\n"
        "Look for SSH keys, deploy keys, or access keys in your Git provider settings."
    )
