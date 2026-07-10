"""Deferred git prerequisite for project create/import onboarding.

git is checked at the moment a checkout actually needs it, not at install
time. Machine-only and dry-run paths never require git; create/import live
applies do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config import project_onboard
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.project_onboard import ProjectOnboardError


def _create_kwargs(checkout: Path) -> dict:
    return {
        "checkout": str(checkout),
        "slug": "demo",
        "name": "Demo",
        "org": None,
        "github_repo": None,
        "default_branch": "main",
        "public_item_prefix": "DMO",
        "github_adoption_choice": "backlog-only",
        "config_path": None,
    }


def test_create_apply_without_git_raises_clean_error(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_git_prerequisite.shutil, "which", lambda _name: None)

    with pytest.raises(ProjectOnboardError) as excinfo:
        project_onboard.create_project(apply=True, **_create_kwargs(tmp_path / "demo"))

    message = str(excinfo.value)
    assert "git is required" in message
    assert "PATH" in message
    # The error fires before any checkout directory is created.
    assert not (tmp_path / "demo").exists()


def test_import_apply_without_git_raises_clean_error(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(project_git_prerequisite.shutil, "which", lambda _name: None)

    with pytest.raises(ProjectOnboardError) as excinfo:
        project_onboard.import_project(
            apply=True,
            remote_url="git@github.com:owner/demo.git",
            **_create_kwargs(tmp_path / "demo"),
        )

    assert "git is required" in str(excinfo.value)


def test_create_dry_run_does_not_require_git(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(project_git_prerequisite.shutil, "which", lambda _name: None)

    report = project_onboard.create_project(apply=False, **_create_kwargs(tmp_path / "demo"))

    assert report["operation"] == "project.create"
    assert report["applied"] is False
