from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_workflow_runs_for_pull_requests_and_pre_releases() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "release:" in workflow
    assert "types: [published]" in workflow
    assert "github.event.release.prerelease == true" in workflow
    assert "ruff check src tests" in workflow
    assert "pytest" in workflow


def test_release_workflow_builds_and_uploads_release_assets() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-build.yml").read_text(encoding="utf-8")

    assert "release:" in workflow
    assert "types: [published]" in workflow
    assert "python -m build" in workflow
    assert ".\\scripts\\dev.ps1 build-exe" in workflow
    assert "gh release upload" in workflow
