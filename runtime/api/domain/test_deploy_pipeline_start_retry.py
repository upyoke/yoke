"""Deployment start refreshes a stale containment answer without a re-drive."""

from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.domain import (
    deploy_pipeline_control_plane as control_plane,
    deploy_pipeline_run_updates as run_updates,
    deployment_run_contained_items as containment,
)

RUN_ID = "run-containment-retry"
STALE = "candidate_containment_attestation_stale"
BASIS = {"primary_project": "project", "basis_digest": "before-merge"}
FRESH_BASIS = {**BASIS, "basis_digest": "after-merge"}


def _refusal(code):
    return SimpleNamespace(
        success=False,
        result=None,
        error=SimpleNamespace(
            code=code, message=f"{code}: refused; Recovery: re-drive"
        ),
    )


def _attest(basis, checkout):
    assert checkout("project") == "/primary"
    return {"basis_digest": basis["basis_digest"]}


def test_start_refreshes_and_reattests_after_concurrent_basis_change(capsys):
    writes = []

    def dispatch(*, function_id, target, payload):
        assert target.workflow_run_id == RUN_ID
        if function_id == "deployment_runs.execution.containment_basis":
            return SimpleNamespace(
                success=True, result={"candidate_containment_basis": FRESH_BASIS}
            )
        assert function_id == "deployment_runs.execution.update"
        writes.append(payload)
        if (
            payload["candidate_containment"]["basis_digest"]
            != FRESH_BASIS["basis_digest"]
        ):
            return _refusal(STALE)
        return SimpleNamespace(success=True, result={"updated": True})

    with (
        mock.patch.object(
            control_plane, "call_dispatcher", side_effect=dispatch
        ) as call,
        mock.patch.object(
            containment, "attest_candidate_containment", side_effect=_attest
        ) as attest,
    ):
        run_updates.start_run(RUN_ID, BASIS, "/primary")

    assert call.call_count == 3
    assert [entry.args[0] for entry in attest.call_args_list] == [BASIS, FRESH_BASIS]
    assert [write["candidate_containment"]["basis_digest"] for write in writes] == [
        "before-merge",
        "after-merge",
    ]
    assert all(write["value"] == "executing" for write in writes)
    assert f"{STALE}; retry 1/3" in capsys.readouterr().out


@pytest.mark.parametrize("code, attempts", [(STALE, 4), ("update_failed", 1)])
def test_start_failure_keeps_bound_and_recovery(code, attempts, capsys):
    with (
        mock.patch.object(
            control_plane, "call_dispatcher", return_value=_refusal(code)
        ) as update,
        mock.patch.object(
            control_plane,
            "containment_basis",
            return_value=FRESH_BASIS,
        ) as refresh,
        mock.patch.object(
            containment, "attest_candidate_containment", side_effect=_attest
        ),
        pytest.raises(run_updates.DeployPipelineRunUpdateError) as failure,
    ):
        run_updates.start_run(RUN_ID, BASIS, "/primary")

    assert update.call_count == attempts
    assert refresh.call_count == attempts - 1
    assert code in str(failure.value)
    assert f"then re-drive {RUN_ID}" in str(failure.value)
    assert capsys.readouterr().out.count("; retry ") == attempts - 1


def test_refresh_failure_keeps_start_recovery():
    with (
        mock.patch.object(
            control_plane, "call_dispatcher", return_value=_refusal(STALE)
        ),
        mock.patch.object(
            control_plane,
            "containment_basis",
            side_effect=control_plane.DeploymentControlPlaneError(
                "connection unavailable"
            ),
        ) as refresh,
        mock.patch.object(
            containment, "attest_candidate_containment", side_effect=_attest
        ),
        pytest.raises(
            run_updates.DeployPipelineRunUpdateError,
            match="connection unavailable.*then re-drive",
        ),
    ):
        run_updates.start_run(RUN_ID, BASIS, "/primary")
    refresh.assert_called_once_with(RUN_ID)
