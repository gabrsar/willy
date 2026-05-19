from pathlib import Path

from willy.ssh import existing_public_keys, is_ssh_remote, setup_instructions


def test_detects_ssh_remote() -> None:
    assert is_ssh_remote("git@example.com:user/repo.git")
    assert is_ssh_remote("ssh://git@example.com/user/repo.git")
    assert not is_ssh_remote("https://example.com/user/repo.git")


def test_existing_public_keys(tmp_path: Path) -> None:
    key = tmp_path / ".ssh" / "id_ed25519.pub"
    key.parent.mkdir()
    key.write_text("ssh-ed25519 abc test\n", encoding="utf-8")

    assert existing_public_keys(tmp_path) == [key]


def test_setup_instructions_include_public_key() -> None:
    instructions = setup_instructions("ssh-ed25519 abc test")

    assert "ssh-ed25519 abc test" in instructions
    assert "Git host" in instructions
