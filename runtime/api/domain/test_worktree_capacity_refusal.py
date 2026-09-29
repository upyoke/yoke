"""The lane-cap refusal names what holds the slots and how to free each kind.

Merging is only the recovery for item lanes. A checkout that filled up with
finished deploy runs' pinned driver trees cannot be merged out of it, so a
refusal that said only "merge existing worktrees" sent its reader looking for
branches those directories do not have.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.worktree_create_plan import (
    DOCTOR_RETIRE_RECIPE,
    preflight_worktree_plan,
)


def _refusal(tmp_path: Path, active_names: list[str]) -> str:
    plan = preflight_worktree_plan(
        [("ITEM-1", str(tmp_path / ".worktrees" / "ITEM-1"))],
        str(tmp_path),
        str(tmp_path / ".worktrees"),
        max_active_worktrees=len(active_names),
        active_count=len(active_names),
        active_names=active_names,
    )
    assert plan.error
    return plan.error


def test_item_lanes_are_told_to_merge(tmp_path: Path) -> None:
    error = _refusal(tmp_path, ["ITEM-7", "ITEM-8"])

    assert "max_active_worktrees limit reached" in error
    assert "Merge existing worktrees before creating more." in error
    assert "Item lanes: ITEM-7, ITEM-8." in error
    assert "deploy-run" not in error


def test_deploy_run_lanes_are_told_the_recovery_that_frees_them(
    tmp_path: Path,
) -> None:
    error = _refusal(
        tmp_path, ["deploy-run-20260101-001", "deploy-run-20260101-002"]
    )

    assert "2 slot(s) are held by deploy-run driver trees" in error
    assert "which no merge retires" in error
    # The resolvable invocation, so a reader can copy it straight out.
    assert DOCTOR_RETIRE_RECIPE in error
    assert DOCTOR_RETIRE_RECIPE.startswith("yoke watch doctor -- ")
    # No item lane is holding a slot, so no reader is sent to merge anything.
    assert "Merge existing worktrees" not in error


def test_a_mixed_checkout_reports_both_kinds(tmp_path: Path) -> None:
    error = _refusal(tmp_path, ["ITEM-7", "deploy-run-20260101-001"])

    assert "Item lanes: ITEM-7." in error
    assert "1 slot(s) are held by deploy-run driver trees" in error
    assert "Deploy-run lanes: deploy-run-20260101-001." in error
