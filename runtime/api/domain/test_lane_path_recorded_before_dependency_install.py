"""A lane's path reaches its registry row before anything slow can fail.

Regression: provisioning installed dependencies first and recorded the
path afterwards, so an install that failed, hung, or outlived its caller
left an active lane row with a NULL path — a lane nobody could locate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import worktree_create_provisioning as provisioning
from yoke_core.domain.worktree_create_plan import (
    WorktreeCreationEntry,
    WorktreeCreationPlan,
)


@pytest.fixture
def plan(tmp_path: Path) -> WorktreeCreationPlan:
    entry = WorktreeCreationEntry(
        branch="YOK-1", path=str(tmp_path / "lane"), lane_id=3
    )
    return WorktreeCreationPlan(worktrees=[entry], primary=entry)


@pytest.fixture
def steps(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the provisioning sequence, stubbing every step's own work."""
    recorded: list[str] = []

    def _step(name, result=None):
        def _run(*_args, **_kwargs):
            recorded.append(name)
            return result

        return _run

    monkeypatch.setattr(provisioning, "create_worktree_lane", _step("lane"))
    monkeypatch.setattr(provisioning, "persist_item_worktrees", _step("persist"))
    monkeypatch.setattr(provisioning, "install_lane_dependencies", _step("deps"))
    monkeypatch.setattr(
        provisioning, "provision_worktree_harness_enablement", _step("harness")
    )
    monkeypatch.setattr(
        provisioning, "provision_worktree_folder_trust", _step("trust")
    )
    monkeypatch.setattr(
        provisioning,
        "provision_worktree_test_environment",
        _step("test-environment", ""),
    )
    return recorded


def _provision(plan: WorktreeCreationPlan, tmp_path: Path):
    return provisioning.provision_planned_lanes(
        plan,
        item_id=11,
        repo_root=str(tmp_path),
        base_branch="main",
        project="yoke",
        scripts_dir=str(tmp_path / "scripts"),
        db_path=None,
    )


def test_the_path_is_recorded_before_dependencies_are_installed(
    plan, steps, tmp_path
) -> None:
    outcome = _provision(plan, tmp_path)

    assert outcome.error == ""
    assert steps.index("persist") < steps.index("deps")
    assert steps == ["lane", "persist", "deps", "harness", "trust", "test-environment"]


def test_the_recorded_row_carries_the_lane_path(
    plan, steps, tmp_path, monkeypatch
) -> None:
    recorded: list[tuple] = []
    monkeypatch.setattr(
        provisioning,
        "persist_item_worktrees",
        lambda item_id, lanes, db_path: recorded.append((item_id, list(lanes))),
    )

    _provision(plan, tmp_path)

    assert recorded == [
        (11, [(3, "YOK-1", str(tmp_path / "lane"), "implementation")])
    ]


def test_a_failing_dependency_install_still_leaves_a_recorded_lane(
    plan, steps, tmp_path, monkeypatch
) -> None:
    def _explode(*_args, **_kwargs):
        raise RuntimeError("pip could not build the pinned wheel")

    monkeypatch.setattr(provisioning, "install_lane_dependencies", _explode)

    with pytest.raises(RuntimeError):
        _provision(plan, tmp_path)

    assert "persist" in steps


def test_a_lane_that_was_never_created_records_nothing(
    plan, steps, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        provisioning,
        "create_worktree_lane",
        lambda *_a: "git worktree add failed for worktree 'YOK-1'",
    )

    outcome = _provision(plan, tmp_path)

    assert "git worktree add failed" in outcome.error
    assert outcome.path == ""
    assert outcome.failed_branch == "YOK-1"
    assert steps == []


def test_persistence_failure_names_the_lane_it_already_created(
    plan, steps, tmp_path, monkeypatch
) -> None:
    def _explode(*_args, **_kwargs):
        raise RuntimeError("relay refused")

    monkeypatch.setattr(provisioning, "persist_item_worktrees", _explode)

    outcome = _provision(plan, tmp_path)

    assert "item-lane persistence failed: relay refused" in outcome.error
    assert outcome.path == str(tmp_path / "lane")
    assert outcome.created is True
    assert "deps" not in steps
