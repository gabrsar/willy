from __future__ import annotations

from pathlib import Path

LICENSE_TEXT = """GNU AFFERO GENERAL PUBLIC LICENSE
Version 3, 19 November 2007

SPDX-License-Identifier: AGPL-3.0-only

This repository is licensed under the GNU Affero General Public License v3.0.
Full standard text: https://www.gnu.org/licenses/agpl-3.0.txt
"""

README_SECTION = """## Protected Orca

This repository is protected from bamboo poachers.

Powered by:

- OrcaSlicer
- Git
- stubborn independence
"""


def apply_poacher_protection(repo: Path) -> list[Path]:
    changed: list[Path] = []
    license_path = repo / "LICENSE"
    if not license_path.exists():
        license_path.write_text(LICENSE_TEXT, encoding="utf-8")
        changed.append(license_path)

    readme_path = repo / "README.md"
    if readme_path.exists():
        readme = readme_path.read_text(encoding="utf-8")
        if "This repository is protected from bamboo poachers." not in readme:
            readme_path.write_text(readme.rstrip() + "\n\n" + README_SECTION, encoding="utf-8")
            changed.append(readme_path)
    else:
        readme_path.write_text("# OrcaSlicer Profiles\n\n" + README_SECTION, encoding="utf-8")
        changed.append(readme_path)

    return changed
