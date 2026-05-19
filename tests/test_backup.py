import json
from pathlib import Path

from willy.backup import create_backup, list_backups


def test_create_backup_copies_tree_and_manifest(tmp_path: Path) -> None:
    source = tmp_path / "orca-user"
    source.mkdir()
    (source / "profile.json").write_text("{}\n", encoding="utf-8")
    backups_dir = tmp_path / "backups"

    backup = create_backup(source, backups_dir, reason="setup")

    assert (backup.path / "profile.json").read_text(encoding="utf-8") == "{}\n"
    manifest = json.loads((backup.path / ".willy-backup.json").read_text(encoding="utf-8"))
    assert manifest["reason"] == "setup"
    assert list_backups(backups_dir) == [backup]
