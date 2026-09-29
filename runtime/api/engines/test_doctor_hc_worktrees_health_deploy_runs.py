"""HC-worktree-health reports finished deploy-run lanes and retires them on --fix.

A self-deploy run's driver worktree has no branch and no owning item, so the
lane-ownership reads the rest of this check is built on have nothing to say
about one. These tests pin what the check does with the deploy-run pass
instead: a run still going is silent, a finished one is a finding, and --fix
turns the finding into a repair.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from runtime.api.engines._doctor_hc_git_test_helpers import (
    _completed,
    _make_conn,
    _result,
    _run_hc,
)
from yoke_core.engines.deploy_run_worktree_retirement import (
    LANE_BLOCKED,
    LANE_RETIRABLE,
    LANE_RETIRED,
    LANE_RUN_OPEN,
    DeployRunLane,
)
from yoke_core.engines.doctor import hc_worktree_health


_HEALTH = "yoke_core.engines.doctor_hc_worktrees_health"
# Only the main checkout, so the item-lane half of the check finds nothing and
# each test reads as a statement about the deploy-run pass alone.
_ONLY_MAIN = "worktree /fake/repo\nbranch refs/heads/main\n\n"


def _lane(run_id: str, state: str, reason: str = "") -> DeployRunLane:
    return DeployRunLane(
        Path(f"/fake/repo/.worktrees/deploy-{run_id}"), run_id, state, reason
    )


def _check(lanes, *, fix: bool = False):
    """Run the HC with the deploy-run sweep answering with *lanes*."""
    with (
        patch("yoke_cli.config.credentialed_git.run"),
        patch(f"{_HEALTH}._base._resolve_repo_root", return_value="/fake/repo"),
        patch(f"{_HEALTH}._base._run", return_value=_completed(stdout=_ONLY_MAIN)),
        patch(
            f"{_HEALTH}.assess_deploy_run_worktrees", return_value=tuple(lanes)
        ) as assessed,
        patch(
            f"{_HEALTH}.retire_terminal_deploy_run_worktrees",
            return_value=tuple(lanes),
        ) as retired,
        patch.object(Path, "is_dir", return_value=False),
    ):
        rec = _run_hc(hc_worktree_health, _make_conn(), fix=fix)
    return rec, assessed, retired


def test_a_run_still_going_is_not_a_finding():
    rec, _assessed, _retired = _check(
        [_lane("run-20260101-001", LANE_RUN_OPEN, "run is executing")]
    )

    assert _result(rec).result == "PASS"
    assert "deploy-run" not in _result(rec).detail


def test_a_finished_run_is_reported_with_its_recovery():
    rec, _assessed, _retired = _check(
        [_lane("run-20260101-002", LANE_RETIRABLE)]
    )

    detail = _result(rec).detail
    assert _result(rec).result == "WARN"
    assert "Finished deploy-run worktree" in detail
    assert "run-20260101-002" in detail
    assert "--fix retires it" in detail
    assert "finished deploy run (run-20260101-002)" in detail


def test_a_blocked_finished_run_names_what_survived():
    rec, _assessed, _retired = _check(
        [
            _lane(
                "run-20260101-003",
                LANE_BLOCKED,
                "unknown ignored files present: operator-scratch.txt",
            )
        ]
    )

    detail = _result(rec).detail
    assert _result(rec).result == "WARN"
    assert "operator-scratch.txt" in detail


def test_without_fix_the_read_only_assessment_runs():
    _rec, assessed, retired = _check([_lane("run-20260101-004", LANE_RETIRABLE)])

    assert assessed.called
    assert not retired.called


def test_fix_retires_and_reports_the_repair():
    rec, assessed, retired = _check(
        [_lane("run-20260101-005", LANE_RETIRED)], fix=True
    )

    detail = _result(rec).detail
    assert retired.called
    assert not assessed.called
    assert "Fixed: retired finished deploy-run worktree" in detail
    assert "run-20260101-005" in detail
    assert _result(rec).result == "PASS"
