from pathlib import Path

from willy.files import classify_path, trackable_paths


def test_classifies_default_profile_json(tmp_path: Path) -> None:
    profile = tmp_path / "default" / "filament" / "ABS.json"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}\n", encoding="utf-8")

    result = classify_path(tmp_path, profile)

    assert result.trackable
    assert result.profile_type == "filament"
    assert result.relative_path == Path("default/filament/ABS.json")


def test_classifies_user_id_profile_json(tmp_path: Path) -> None:
    profile = tmp_path / "2765349417" / "process" / "Fast.json"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}\n", encoding="utf-8")

    result = classify_path(tmp_path, profile)

    assert result.trackable
    assert result.profile_type == "process"
    assert result.relative_path == Path("2765349417/process/Fast.json")


def test_ignores_git_and_temp_files(tmp_path: Path) -> None:
    git_file = tmp_path / ".git" / "config"
    tmp_file = tmp_path / "default" / "process" / "profile.tmp"
    git_file.parent.mkdir(parents=True)
    tmp_file.parent.mkdir(parents=True)
    git_file.write_text("", encoding="utf-8")
    tmp_file.write_text("", encoding="utf-8")

    assert not classify_path(tmp_path, git_file).trackable
    assert not classify_path(tmp_path, tmp_file).trackable


def test_info_sidecars_are_not_tracked_in_v1(tmp_path: Path) -> None:
    sidecar = tmp_path / "default" / "machine" / "Printer.info"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("setting_id = PMUS\n", encoding="utf-8")

    result = classify_path(tmp_path, sidecar)

    assert not result.trackable
    assert result.profile_type == "machine"


def test_trackable_paths_returns_json_only(tmp_path: Path) -> None:
    tracked = tmp_path / "default" / "process" / "Fast.json"
    ignored = tmp_path / "default" / "process" / "Fast.info"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("{}\n", encoding="utf-8")
    ignored.write_text("setting_id = PPUS\n", encoding="utf-8")

    assert trackable_paths(tmp_path) == [tracked]


def test_asset_files_are_tracked_only_inside_configured_asset_dirs(tmp_path: Path) -> None:
    asset_dir = tmp_path / "prints"
    tracked = asset_dir / "benchy.3mf"
    ignored = tmp_path / "loose" / "benchy.stl"
    tracked.parent.mkdir(parents=True)
    ignored.parent.mkdir(parents=True)
    tracked.write_text("model\n", encoding="utf-8")
    ignored.write_text("solid model\n", encoding="utf-8")

    tracked_result = classify_path(tmp_path, tracked, asset_dirs=(asset_dir,))
    ignored_result = classify_path(tmp_path, ignored, asset_dirs=(asset_dir,))

    assert tracked_result.trackable
    assert tracked_result.profile_type == "asset"
    assert not ignored_result.trackable
    assert trackable_paths(tmp_path, asset_dirs=(asset_dir,)) == [tracked]
