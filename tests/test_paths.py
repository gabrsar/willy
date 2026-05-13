from pathlib import Path

from willy.paths import default_paths, expand_path


def test_default_paths_are_under_home() -> None:
    home = Path("/tmp/willy-home")
    paths = default_paths(home)

    assert paths.root == home / ".willy"
    assert paths.config_file == home / ".willy" / "config.toml"
    assert paths.default_orca_user_dir == home / "Library" / "Application Support" / "OrcaSlicer" / "user"


def test_expand_path_uses_supplied_home() -> None:
    home = Path("/tmp/willy-home")

    assert expand_path("~/profiles", home=home) == home / "profiles"
    assert expand_path("relative/path", home=home) == Path("relative/path")
