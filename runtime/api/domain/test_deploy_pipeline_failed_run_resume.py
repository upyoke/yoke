"""A plain resume of a failed pipeline re-enters executing at the failed stage.

The run flips to executing before any receipt allocate and does not dispatch
completed stages. Failed receipts stay; this path is not --retry-of. Only
the stage that failed is told to retry its failed workflow run, and there is
no ``--from-stage``.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import (
    deploy_pipeline,
    deploy_pipeline_run_context,
    deploy_pipeline_run_updates,
    deploy_pipeline_stage_checks,
)
from yoke_core.domain.deploy_pipeline_cli import _build_parser
from yoke_core.domain.deploy_pipeline_stage_checks import retry_failed_stage


def test_failed_run_resume_reenters_executing_without_replay(capsys):
    run_id = "run-20260917-012"
    context = {
        "run": {
            "id": run_id,
            "project": "yoke",
            "flow": "yoke-hosted-production-release-qa",
            "target_tier": "persistent",
            "target_environment": "prod",
            "release_lineage": "a" * 40,
            "status": "failed",
            "current_stage": "warm-up-failed",
        },
        "members": [],
        "stages": [
            {
                "name": "hosted-release",
                "step_runner": "github-actions-workflow",
            },
            {"name": "warm-up", "step_runner": "warm-up"},
            {"name": "complete", "step_runner": "auto"},
        ],
    }
    run_mutations = []
    dispatched = []

    def fake_update_run_field(mutated_run, field, value):
        run_mutations.append((mutated_run, field, value))

    def fake_dispatch(stage, **_kwargs):
        dispatched.append(stage["name"])
        return 0, ""

    with (
        mock.patch.object(
            deploy_pipeline,
            "resolve_flow_gate_branch",
            return_value="main",
        ),
        mock.patch.object(
            deploy_pipeline.control_plane,
            "execution_context",
            return_value=context,
        ),
        mock.patch.object(
            deploy_pipeline_run_updates,
            "update_run_field",
            side_effect=fake_update_run_field,
        ),
        mock.patch.object(
            deploy_pipeline_run_updates,
            "start_run",
            side_effect=lambda started_run, _basis, _checkout: fake_update_run_field(
                started_run, "status", "executing"
            ),
        ),
        mock.patch.object(
            deploy_pipeline.control_plane,
            "project_field",
            return_value="",
        ),
        mock.patch.object(
            deploy_pipeline,
            "resolve_project_checkout_path",
            return_value="/repo",
        ),
        mock.patch.object(
            deploy_pipeline_stage_checks,
            "check_resume_qa_gate",
            return_value=None,
        ),
        mock.patch.object(
            deploy_pipeline.stage_receipt,
            "dispatch_step_runner_with_receipt",
            side_effect=fake_dispatch,
        ),
        mock.patch.object(deploy_pipeline, "_emit_run_event"),
        mock.patch.object(deploy_pipeline_run_context, "_emit_run_event"),
        mock.patch.object(
            deploy_pipeline.control_plane,
            "unresolved_qa",
            return_value=[],
        ),
    ):
        rc = deploy_pipeline.run_pipeline(run_id, sd="/tmp/sd")

    assert rc == deploy_pipeline.EXIT_SUCCESS
    assert "hosted-release" not in dispatched
    assert dispatched == ["warm-up", "complete"]
    status_updates = [
        value
        for mutated_run, field, value in run_mutations
        if (mutated_run, field) == (run_id, "status")
    ]
    assert status_updates[0] == "executing"
    assert "failed" not in status_updates
    assert status_updates[-1] == "succeeded"
    stage_updates = [
        value
        for mutated_run, field, value in run_mutations
        if (mutated_run, field) == (run_id, "current_stage")
    ]
    assert "hosted-release" not in stage_updates
    assert stage_updates[0] == "warm-up"
    out = capsys.readouterr().out
    assert "--- Stage: hosted-release" not in out
    assert "--- Stage: warm-up" in out


def _dispatch_flags(
    status: str, current_stage: str, run_id: str
) -> dict[str, tuple[bool, bool]]:
    context = {
        "run": {
            "id": run_id,
            "project": "yoke",
            "flow": "yoke-hosted-production-release-qa",
            "target_tier": "persistent",
            "target_environment": "prod",
            "release_lineage": "a" * 40,
            "status": status,
            "current_stage": current_stage,
        },
        "members": [],
        "stages": [
            {
                "name": "hosted-release",
                "step_runner": "github-actions-workflow",
            },
            {"name": "warm-up", "step_runner": "warm-up"},
            {"name": "complete", "step_runner": "auto"},
        ],
    }
    flags: dict[str, tuple[bool, bool]] = {}

    def fake_dispatch(stage, **kwargs):
        flags[stage["name"]] = (kwargs["fresh"], kwargs["retry_failed"])
        return 0, ""

    with (
        mock.patch.object(
            deploy_pipeline,
            "resolve_flow_gate_branch",
            return_value="main",
        ),
        mock.patch.object(
            deploy_pipeline.control_plane,
            "execution_context",
            return_value=context,
        ),
        mock.patch.object(deploy_pipeline_run_updates, "update_run_field"),
        mock.patch.object(deploy_pipeline_run_updates, "start_run"),
        mock.patch.object(
            deploy_pipeline.control_plane,
            "project_field",
            return_value="",
        ),
        mock.patch.object(
            deploy_pipeline,
            "resolve_project_checkout_path",
            return_value="/repo",
        ),
        mock.patch.object(
            deploy_pipeline_stage_checks,
            "check_resume_qa_gate",
            return_value=None,
        ),
        mock.patch.object(
            deploy_pipeline.stage_receipt,
            "dispatch_step_runner_with_receipt",
            side_effect=fake_dispatch,
        ),
        mock.patch.object(deploy_pipeline, "_emit_run_event"),
        mock.patch.object(deploy_pipeline_run_context, "_emit_run_event"),
        mock.patch.object(
            deploy_pipeline.control_plane,
            "unresolved_qa",
            return_value=[],
        ),
    ):
        rc = deploy_pipeline.run_pipeline(run_id, sd="/tmp/sd")

    assert rc == deploy_pipeline.EXIT_SUCCESS
    return flags


def test_only_the_failed_stage_of_a_failed_run_retries_its_workflow_run():
    run_id = "run-20261023-007"
    stage = "hosted-release"

    assert retry_failed_stage("failed", stage, stage) is True
    assert retry_failed_stage("failed", stage, "warm-up") is False
    assert retry_failed_stage("failed", "", stage) is False
    assert retry_failed_stage("executing", stage, stage) is False

    failed = _dispatch_flags("failed", f"{stage}-failed", run_id)
    assert failed == {
        stage: (False, True),
        "warm-up": (False, False),
        "complete": (False, False),
    }

    executing = _dispatch_flags("executing", stage, run_id)
    assert executing[stage] == (False, False)


def test_from_stage_is_rejected_as_unknown(capsys):
    with pytest.raises(SystemExit) as exit_info:
        _build_parser().parse_args(["run-x", "--from-stage", "hosted-release"])

    assert exit_info.value.code == 2
    assert "unrecognized arguments: --from-stage" in capsys.readouterr().err
