"""Regression coverage for onboarding an existing-folder path that is missing.

``onboard_existing`` used to raise "checkout is not a directory" for a
not-yet-existing path before the dry-run branch, so the wizard's Finish preview
rendered an error body instead of a write-plan — while create_project (which
makes the folder at apply) accepted identical input. The fix tolerates a missing
folder: the dry-run reports it as a folder Yoke will create, and apply makes
the directory + git repo, mirroring create_project. A path that exists as a
regular file (not a directory) stays a hard error.

These call ``onboard_existing`` directly. The dry-run path performs no dispatch
or network I/O, so no backend stub is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config import project_onboard
from yoke_cli.config import project_onboard_apply
from yoke_cli.config.project_onboard_support import ProjectOnboardError


def _base_kwargs(checkout: Path) -> dict:
    return {
        "checkout": str(checkout),
        "slug": "widget",
        "name": "Widget",
        "org": None,
        "github_repo": None,
        "default_branch": "main",
        "public_item_prefix": "WIDG",
        "github_adoption_choice": "backlog-only",
        "config_path": None,
    }


@pytest.fixture
def _stub_backend(monkeypatch):
    """Stub dispatch + install + machine register so apply runs the git ops only.

    ``projects.get`` raises not_found so apply creates the project; the report
    assembly is stubbed since these assert the on-disk folder + repo creation,
    not the report shape.
    """
    def _fake_dispatch(function_id, payload, config_path):
        if function_id == "projects.get":
            raise project_onboard.ProjectDispatchError(
                function_id, "not_found", "missing"
            )
        return {"project": {"id": 7, "slug": payload.get("slug")}}

    monkeypatch.setattr(project_onboard, "dispatch", _fake_dispatch)
    monkeypatch.setattr(
        project_onboard_apply.install_runner, "install",
        lambda *a, **k: {"installed": True},
    )
    monkeypatch.setattr(
        project_onboard_apply.machine_writer, "register_project",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        project_onboard_apply, "applied_report",
        lambda *a, **k: {"applied": True},
    )


def test_dry_run_on_missing_folder_returns_plan_without_raising(tmp_path: Path) -> None:
    """A not-yet-existing path previews as a folder Yoke will create."""
    missing = tmp_path / "not-created-yet"
    assert not missing.exists()

    report = project_onboard.onboard_existing(apply=False, **_base_kwargs(missing))

    assert report["applied"] is False
    # The missing folder reads as new-local, the same as create_project's
    # dry-run for a fresh checkout — never the existing-local mode that implies
    # the folder is already there.
    assert report["checkout"] == {
        "path": str(missing.resolve()),
        "mode": "new-local",
    }
    # The plan is intact and the folder is still untouched by the dry-run.
    assert report["plan"]
    assert not missing.exists()


def test_dry_run_on_existing_folder_reports_existing_local(tmp_path: Path) -> None:
    """An existing folder still previews as existing-local (unchanged)."""
    folder = tmp_path / "already-here"
    folder.mkdir()

    report = project_onboard.onboard_existing(apply=False, **_base_kwargs(folder))

    assert report["checkout"]["mode"] == "existing-local"


def test_dry_run_hard_errors_on_path_that_is_a_regular_file(tmp_path: Path) -> None:
    """A path that exists as a plain file cannot become a checkout."""
    plain_file = tmp_path / "a-file"
    plain_file.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(ProjectOnboardError, match="checkout is not a directory"):
        project_onboard.onboard_existing(apply=False, **_base_kwargs(plain_file))


def test_apply_on_missing_folder_creates_directory_and_git_repo(
    tmp_path: Path, _stub_backend
) -> None:
    """Apply makes the folder and a git repo, parity with create_project."""
    missing = tmp_path / "to-be-created"
    assert not missing.exists()

    project_onboard.onboard_existing(apply=True, **_base_kwargs(missing))

    assert missing.is_dir()
    assert (missing / ".git").is_dir()
