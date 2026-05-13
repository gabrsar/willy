from pathlib import Path

from willy.protection import apply_poacher_protection


def test_apply_poacher_protection_creates_license_and_readme(tmp_path: Path) -> None:
    changed = apply_poacher_protection(tmp_path)

    assert tmp_path / "LICENSE" in changed
    assert tmp_path / "README.md" in changed
    assert "AGPL-3.0-only" in (tmp_path / "LICENSE").read_text(encoding="utf-8")
    assert "protected from bamboo poachers" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_apply_poacher_protection_is_idempotent(tmp_path: Path) -> None:
    apply_poacher_protection(tmp_path)

    changed = apply_poacher_protection(tmp_path)

    assert changed == []
