from pathlib import Path

from willy.metadata import (
    change_type_from_status,
    commit_body,
    commit_subject,
    extract_metadata,
    infer_filament,
)


def test_extracts_filament_metadata(tmp_path: Path) -> None:
    path = tmp_path / "default" / "filament" / "3D Fila - ABS - V1.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"name": "3D Fila - ABS - V1"}\n', encoding="utf-8")

    metadata = extract_metadata(tmp_path, Path("default/filament/3D Fila - ABS - V1.json"))

    assert metadata.profile_type == "filament"
    assert metadata.filament_type == "ABS"
    assert metadata.profile_name == "3D Fila - ABS - V1"


def test_extracts_machine_metadata(tmp_path: Path) -> None:
    path = tmp_path / "default" / "machine" / "Printer.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"name": "Prusa Core One"}\n', encoding="utf-8")

    metadata = extract_metadata(tmp_path, Path("default/machine/Printer.json"))

    assert metadata.profile_type == "machine"
    assert metadata.printer_name == "Prusa Core One"


def test_metadata_survives_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "default" / "process" / "Fast.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad json", encoding="utf-8")

    metadata = extract_metadata(tmp_path, Path("default/process/Fast.json"))

    assert metadata.profile_type == "process"
    assert metadata.profile_name == "Fast"


def test_commit_formatters() -> None:
    metadata = extract_metadata(Path("/tmp"), Path("default/process/Fast.json"))

    subject = commit_subject("modified", metadata, Path("default/process/Fast.json"))
    body = commit_body(
        metadata=metadata, event="modified", relative_path=Path("default/process/Fast.json"), description="tuned speed"
    )

    assert subject == "modified | process | unknown | unknown | default/process/Fast.json"
    assert "Profile-Type: process" in body
    assert "tuned speed" in body


def test_change_type_and_filament_inference() -> None:
    assert change_type_from_status("??") == "created"
    assert change_type_from_status(" M") == "modified"
    assert change_type_from_status("D ") == "deleted"
    assert infer_filament("my petg profile") == "PETG"
