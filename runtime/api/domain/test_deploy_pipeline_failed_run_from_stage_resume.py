"""Same-run --from-stage resume of a failed pipeline re-enters executing.

A failed run whose current_stage is already the resume point must flip
status to executing before any receipt allocate, and must not dispatch
skipped completed stages. Failed receipts stay; this path is not --retry-of.
"""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import (
    deploy_pipeline,
    deploy_pipeline_run_context,
    deploy_pipeline_run_updates,
    deploy_pipeline_stage_checks,
)
from yoke_core.domain.deploy_pipeline_github_workflow_inputs import (
    fresh_retrigger_scope,
    workflow_dispatch_request_id,
)
from yoke_core.domain.deploy_pipeline_stage_checks import fresh_resume


def test_failed_from_stage_resume_reenters_executing_without_replay(capsys):
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
            "current_stage": "warm-up",
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
        rc = deploy_pipeline.run_pipeline(run_id, from_stage="warm-up", sd="/tmp/sd")

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


def _fresh_flags(status: str, from_stage: str, run_id: str) -> dict[str, bool]:
    context = {
        "run": {
            "id": run_id,
            "project": "yoke",
            "flow": "yoke-hosted-production-release-qa",
            "target_tier": "persistent",
            "target_environment": "prod",
            "release_lineage": "a" * 40,
            "status": status,
            "current_stage": from_stage,
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
    flags: dict[str, bool] = {}

    def fake_dispatch(stage, **kwargs):
        flags[stage["name"]] = kwargs["fresh"]
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
        rc = deploy_pipeline.run_pipeline(run_id, from_stage=from_stage, sd="/tmp/sd")

    assert rc == deploy_pipeline.EXIT_SUCCESS
    return flags


def test_failed_from_stage_dispatches_fresh_and_executing_keeps_base_request_id():
    run_id = "run-20261023-007"
    stage = "hosted-release"
    project = "yoke"
    base = workflow_dispatch_request_id(project, run_id, stage)

    assert fresh_resume("failed", stage, stage) is True
    assert fresh_resume("failed", stage, "warm-up") is False
    assert fresh_resume("failed", "", stage) is False
    assert fresh_resume("executing", stage, stage) is False

    failed = _fresh_flags("failed", stage, run_id)
    assert failed[stage] is True
    assert failed["warm-up"] is False
    scoped = workflow_dispatch_request_id(
        project,
        run_id,
        stage,
        retrigger_scope=fresh_retrigger_scope(),
    )
    assert scoped.startswith(f"{base}:fresh:")

    executing = _fresh_flags("executing", stage, run_id)
    assert executing[stage] is False
    assert workflow_dispatch_request_id(project, run_id, stage) == base
