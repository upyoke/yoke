"""Fail-closed workflow reconciliation and retrigger idempotency coverage."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)
from yoke_core.domain import deploy_pipeline_github_workflow as workflow
from yoke_core.domain import (
    deploy_pipeline_github_workflow_inputs as workflow_inputs,
)
from yoke_core.domain.deploy_preview_dispatch_boundary import (
    release_preview_origin,
)
from yoke_core.domain.ephemeral_substrate import preview_url

LINEAGE = "a" * 40
PREVIEW_PROJECT = "webapp"
PREVIEW_RUN = "run-20260915-001"
PREVIEW_STAGE = "release-preview"
PREVIEW_DOMAIN = "preview.example.test"
#: The stage a release preview is dispatched from, and the name it carries.
PREVIEW_STAGE_CONFIG = {
    "workflow": "webapp-ephemeral.yml",
    "dispatch_correlation_input": WORKFLOW_DISPATCH_CORRELATION_INPUT,
    "inputs": {"commit_sha": "{head_sha}", "preview_slug": "{preview_slug}"},
}


def _result(
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def test_find_run_transport_failure_is_not_treated_as_not_found() -> None:
    with mock.patch.object(
        workflow,
        "_github_actions",
        return_value=_result(4, stderr="relay unavailable"),
    ), pytest.raises(workflow._WorkflowReconciliationError) as raised:
        workflow._find_existing_workflow_run(
            "upyoke/platform",
            "deploy.yml",
            "abc123",
            project="platform",
            sd=None,
        )

    assert "find-run" in str(raised.value)
    assert "relay unavailable" in str(raised.value)


def test_jobs_count_transport_failure_is_not_treated_as_zero() -> None:
    with mock.patch.object(
        workflow,
        "_github_actions",
        side_effect=[
            _result(0, stdout="77\n"),
            _result(4, stderr="hosted handler unavailable"),
        ],
    ), pytest.raises(workflow._WorkflowReconciliationError) as raised:
        workflow._find_existing_workflow_run(
            "upyoke/platform",
            "deploy.yml",
            "abc123",
            project="platform",
            sd=None,
        )

    assert "jobs-count" in str(raised.value)
    assert "hosted handler unavailable" in str(raised.value)


def test_empty_and_failed_predecessors_get_deterministic_retrigger_scopes() -> None:
    with mock.patch.object(
        workflow,
        "_github_actions",
        side_effect=[_result(0, "77\n"), _result(0, "0\n")],
    ):
        empty = workflow._find_existing_workflow_run(
            "upyoke/platform",
            "deploy.yml",
            "abc123",
            project="platform",
            sd=None,
        )

    with mock.patch.object(
        workflow,
        "_github_actions",
        side_effect=[
            _result(0, "88\n"),
            _result(0, "2\n"),
            _result(1, "failed:failure\n"),
        ],
    ):
        failed = workflow._find_existing_workflow_run(
            "upyoke/platform",
            "deploy.yml",
            "abc123",
            project="platform",
            sd=None,
        )

    assert empty == ("", False, "empty:77")
    assert failed == ("", False, "failed:88")


def test_stale_failed_run_scope_reaches_workflow_dispatch_request_id() -> None:
    github_calls: list[tuple[str, ...]] = []

    def _github_actions(*args: str, **_kwargs: object) -> subprocess.CompletedProcess:
        github_calls.append(args)
        return _result(0, "99\n")

    with mock.patch.object(
        workflow, "_check_ci_gate", return_value=(True, ""),
    ), mock.patch.object(
        workflow, "_run_cmd", return_value=_result(0, "abc123\n"),
    ), mock.patch.object(
        workflow,
        "_find_existing_workflow_run",
        return_value=("", False, "failed:88"),
    ), mock.patch.object(
        workflow, "_github_actions", side_effect=_github_actions,
    ), mock.patch.object(
        workflow, "_poll_github_actions", return_value=(0, "success"),
    ):
        result = workflow._dispatch_github_actions_workflow(
            {"workflow": "deploy.yml", "dispatch_correlation_input": "yoke_dispatch_id"},
            name="prod-deploy",
            run_id="run-1",
            member_items=[],
            github_repo="upyoke/platform",
            project="platform",
            project_repo_path="",
            timeout_min=30,
            fresh=False,
            gate_branch="main",
            release_lineage="a" * 40,
            sd="/tmp/sd",
        )

    assert result == (0, "")
    trigger = github_calls[0]
    assert trigger[trigger.index("--request-id") + 1] == (
        "deploy:platform:run-1:prod-deploy:failed:88"
    )
    assert trigger[-2:] == ("--correlation-input", "yoke_dispatch_id")


def test_each_explicit_fresh_invocation_gets_a_new_request_scope() -> None:
    github_calls: list[tuple[str, ...]] = []

    def _github_actions(*args: str, **_kwargs: object) -> subprocess.CompletedProcess:
        github_calls.append(args)
        return _result(0, "99\n")

    with mock.patch.object(
        workflow, "_check_ci_gate", return_value=(True, ""),
    ), mock.patch.object(
        workflow, "_run_cmd", return_value=_result(0, "abc123\n"),
    ), mock.patch.object(
        workflow, "_github_actions", side_effect=_github_actions,
    ), mock.patch.object(
        workflow, "_poll_github_actions", return_value=(0, "success"),
    ), mock.patch.object(
        # Minting moved to the shared inputs helper when the release-preview
        # exemption landed; a branch preview's --fresh still gets a new scope.
        workflow_inputs.uuid,
        "uuid4",
        side_effect=[SimpleNamespace(hex="first"), SimpleNamespace(hex="second")],
    ):
        for _ in range(2):
            result = workflow._dispatch_github_actions_workflow(
                {"workflow": "deploy.yml", "dispatch_correlation_input": "yoke_dispatch_id"},
                name="prod-deploy",
                run_id="run-1",
                member_items=[],
                github_repo="upyoke/platform",
                project="platform",
                project_repo_path="",
                timeout_min=30,
                fresh=True,
                gate_branch="main",
                release_lineage="a" * 40,
                sd="/tmp/sd",
            )
            assert result == (0, "")

    request_ids = [
        call[call.index("--request-id") + 1]
        for call in github_calls
        if call and call[0] == "trigger"
    ]
    assert request_ids == [
        "deploy:platform:run-1:prod-deploy:fresh:first",
        "deploy:platform:run-1:prod-deploy:fresh:second",
    ]


def _release_preview_dispatch(*, fresh: bool, calls: list) -> None:
    """Drive one release-preview stage through the real dispatcher."""

    def _github_actions(*args: str, **_kwargs: object) -> subprocess.CompletedProcess:
        calls.append(args)
        return _result(0, "99\n")

    with mock.patch.object(
        workflow, "_check_ci_gate", return_value=(True, ""),
    ), mock.patch.object(
        workflow, "_run_cmd", return_value=_result(0, f"{LINEAGE}\n"),
    ), mock.patch.object(
        workflow, "_github_actions", side_effect=_github_actions,
    ), mock.patch.object(
        workflow, "_poll_github_actions", return_value=(0, "success"),
    ):
        result = workflow._dispatch_github_actions_workflow(
            dict(PREVIEW_STAGE_CONFIG),
            name=PREVIEW_STAGE,
            run_id=PREVIEW_RUN,
            member_items=[],
            github_repo="upyoke/webapp",
            project=PREVIEW_PROJECT,
            project_repo_path="",
            timeout_min=30,
            fresh=fresh,
            gate_branch="main",
            release_lineage=LINEAGE,
            preview_slug=PREVIEW_RUN,
            sd="/tmp/sd",
        )
    assert result == (0, "")


def _trigger_calls(calls: list) -> list[tuple[str, ...]]:
    return [call for call in calls if call and call[0] == "trigger"]


def _sent(call: tuple[str, ...], flag: str) -> str:
    return call[call.index(flag) + 1]


def test_a_release_preview_dispatch_carries_candidate_and_name() -> None:
    """Both, together, or the deploy is not about this run's candidate.

    The revision input pins the commit the preview serves, and the preview
    name input decides the host it is published at. Sending one without the
    other stands up a preview whose URL or whose contents the receipt cannot
    account for. This reads the inputs actually placed on the wire, because
    the defect this closes lived between the resolved inputs and the POST.
    """
    calls: list = []
    _release_preview_dispatch(fresh=False, calls=calls)
    call = _trigger_calls(calls)[0]
    assert f"commit_sha={LINEAGE}" in call
    assert f"preview_slug={PREVIEW_RUN}" in call
    assert _sent(call, "--correlation-input") == WORKFLOW_DISPATCH_CORRELATION_INPUT
    assert _sent(call, "--request-id") == workflow_inputs.workflow_dispatch_request_id(
        PREVIEW_PROJECT, PREVIEW_RUN, PREVIEW_STAGE
    )


def test_the_dispatched_name_is_the_probed_occupancy_url() -> None:
    """The name read off the wire has to be the URL the receipt probes —
    otherwise the dispatch deploys to one host and the proof reads another,
    which is exactly what a correlation-derived name produced."""
    calls: list = []
    _release_preview_dispatch(fresh=False, calls=calls)
    call = _trigger_calls(calls)[0]
    sent_slug = next(
        value.split("=", 1)[1]
        for value in call
        if value.startswith("preview_slug=")
    )

    probed, refusal = release_preview_origin(
        {
            "step_runner": "github-actions-workflow",
            "target": {"kind": "run_preview", "capability": "ephemeral-env"},
            "config": PREVIEW_STAGE_CONFIG,
        },
        project=PREVIEW_PROJECT,
        run_id=PREVIEW_RUN,
        stage_name=PREVIEW_STAGE,
        trigger="github-push",
        preview_domain=PREVIEW_DOMAIN,
    )
    assert refusal == ""
    assert probed == preview_url(sent_slug, PREVIEW_DOMAIN)


def test_a_fresh_release_preview_retrigger_keeps_the_same_occupancy() -> None:
    """``--fresh`` mints a new dispatch scope so GitHub starts a new run.
    The preview's name does not come from that scope, so both dispatches
    still publish the same occupancy — safe because the candidate is frozen,
    and the deploy workflow reuses an occupancy for the same name and commit."""
    calls: list = []
    _release_preview_dispatch(fresh=True, calls=calls)
    _release_preview_dispatch(fresh=True, calls=calls)
    triggered = _trigger_calls(calls)
    request_ids = [_sent(call, "--request-id") for call in triggered]
    assert len(set(request_ids)) == 2
    assert all(f"preview_slug={PREVIEW_RUN}" in call for call in triggered)
