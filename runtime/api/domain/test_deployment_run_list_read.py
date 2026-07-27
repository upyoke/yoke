"""Deployment-run member and segmented-stage projection helpers."""

from yoke_core.domain.deployment_run_list_read import _stage_rows


def test_executing_stage_marks_prior_complete_and_current_active():
    rows, index = _stage_rows(
        ["build", "verify", "release"],
        current="verify",
        status="executing",
    )
    assert index == 1
    assert rows == [
        {"name": "build", "state": "complete"},
        {"name": "verify", "state": "active"},
        {"name": "release", "state": "pending"},
    ]


def test_failed_and_succeeded_runs_project_terminal_stage_states():
    failed, _ = _stage_rows(
        ["build", "verify"],
        current="verify",
        status="failed",
    )
    assert [row["state"] for row in failed] == ["complete", "failed"]
    succeeded, succeeded_index = _stage_rows(
        ["build", "verify"],
        current="complete",
        status="succeeded",
    )
    assert [row["state"] for row in succeeded] == ["complete", "complete"]
    assert succeeded_index == 1
