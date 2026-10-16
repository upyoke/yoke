"""The lane cap counts lanes doing work and names how to free each kind.

Merging is only the recovery for unmerged item lanes. A lane that already
landed holds no slot. A finished deploy run's pinned driver tree cannot be
merged out of a full checkout; an open run's driver tree is in use and must
never be offered for retirement.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_core.domain import worktree_capacity
from yoke_core.domain.worktree_capacity import DOCTOR_RETIRE_RECIPE
from yoke_core.domain.worktree_create_plan import preflight_worktree_plan
from yoke_core.engines.deploy_run_worktree_retirement import (
    LANE_RETIRABLE,
    LANE_RUN_OPEN,
    DeployRunLane,
)


def _refusal(tmp_path: Path, active_names: list[str]) -> str:
    plan = preflight_worktree_plan(
        [("ITEM-1", str(tmp_path / ".worktrees" / "ITEM-1"))],
        str(tmp_path),
        str(tmp_path / ".worktrees"),
        max_active_worktrees=len(active_names),
        active_count=len(active_names),
        active_names=active_names,
        landed_base="main",
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
    error = _refusal(tmp_path, ["deploy-run-20260101-001", "deploy-run-20260101-002"])

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


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _commit(repo: Path, message: str) -> None:
    # A real change: git's patch-equivalence proof treats an empty commit as
    # already carried by any base.
    (repo / f"{message.replace(' ', '-')}.txt").write_text(message)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message)


def _repo_with_landed_and_unmerged_lane(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _commit(repo, "base")
    _git(repo, "worktree", "add", "-b", "ITEM-7", str(repo / ".worktrees" / "ITEM-7"))
    _git(repo, "worktree", "add", "-b", "ITEM-8", str(repo / ".worktrees" / "ITEM-8"))
    _commit(repo / ".worktrees" / "ITEM-7", "landed work")
    _git(repo, "merge", "--ff-only", "ITEM-7")
    _commit(repo / ".worktrees" / "ITEM-8", "unlanded work")
    return repo


def test_a_lane_that_has_not_committed_yet_still_counts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _commit(repo, "base")
    _git(repo, "worktree", "add", "-b", "ITEM-7", str(repo / ".worktrees" / "ITEM-7"))

    landed = worktree_capacity.landed_item_lanes(str(repo), ["ITEM-7"], "main")

    assert landed == set()


def _plan(repo: Path, cap: int):
    return preflight_worktree_plan(
        [("ITEM-1", str(repo / ".worktrees" / "ITEM-1"))],
        str(repo),
        str(repo / ".worktrees"),
        max_active_worktrees=cap,
        active_count=2,
        active_names=["ITEM-7", "ITEM-8"],
        landed_base="main",
    )


def test_landed_item_lanes_do_not_block_creation_at_the_cap(tmp_path: Path) -> None:
    repo = _repo_with_landed_and_unmerged_lane(tmp_path)

    plan = _plan(repo, cap=2)

    assert plan.error is None
    assert not plan.capacity_refused


def test_a_refusal_counts_only_unmerged_lanes(tmp_path: Path) -> None:
    repo = _repo_with_landed_and_unmerged_lane(tmp_path)

    error = _plan(repo, cap=1).error

    assert error
    assert "(1 active + 1 pending > 1; 1 landed lane(s) not counted)" in error
    assert "Item lanes: ITEM-8." in error
    assert "ITEM-7" not in error


def test_doctor_lists_landed_lanes_apart(tmp_path: Path) -> None:
    repo = _repo_with_landed_and_unmerged_lane(tmp_path)

    def run_git(args, *, cwd=None, capture=True):
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True
        )

    note = worktree_capacity.landed_lanes_note(
        run_git, str(repo), [("ITEM-7", "ITEM-7", "main"), ("ITEM-8", "ITEM-8", "main")]
    )

    assert note == (
        "- 1 landed lane(s) await release close-out and are not counted "
        "against max_active_worktrees: ITEM-7"
    )


def test_an_open_runs_driver_tree_is_in_use_not_retirable(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        worktree_capacity,
        "assess_deploy_run_worktrees",
        lambda **_kw: (
            DeployRunLane(tmp_path / "deploy-run-open", "run-open", LANE_RUN_OPEN),
            DeployRunLane(tmp_path / "deploy-run-done", "run-done", LANE_RETIRABLE),
        ),
    )

    error = _refusal(tmp_path, ["deploy-run-open", "deploy-run-done"])

    assert "1 slot(s) are in use by open deploy runs' drivers" in error
    assert "In-use deploy-run lanes: deploy-run-open." in error
    assert "Deploy-run lanes: deploy-run-done." in error
    retirable = error.split("In-use deploy-run lanes")[0]
    assert "deploy-run-open" not in retirable
