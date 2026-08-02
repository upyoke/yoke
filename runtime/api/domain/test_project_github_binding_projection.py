# ruff: noqa: F401, F811
"""Project-field protections for a verified GitHub binding."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_project_github_binding_fanout import (
    bound_yoke_db,
)
from yoke_core.domain import projects
from yoke_core.domain.projects_upsert import cmd_upsert


def test_project_upsert_rejects_repo_change_after_binding(bound_yoke_db) -> None:
    with pytest.raises(ValueError, match="binding-owned"):
        cmd_upsert(
            slug="yoke",
            name="Yoke",
            github_repo="other-org/other-repo",
            mode="update",
        )
    assert projects.cmd_get("yoke", field="github_repo") == "Example-Org/Yoke"


def test_project_upsert_accepts_equivalent_repo_and_keeps_bound_projection(
    bound_yoke_db,
) -> None:
    cmd_upsert(
        slug="yoke",
        name="Yoke Renamed",
        github_repo="https://github.com/example-org/yoke.git",
        mode="update",
    )
    assert projects.cmd_get("yoke", field="github_repo") == "Example-Org/Yoke"


def test_legacy_project_field_update_cannot_bypass_binding(bound_yoke_db) -> None:
    with pytest.raises(ValueError, match="binding-owned"):
        projects.cmd_update("yoke", "github_repo", "other-org/other-repo")
