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
            deploy_pipeline.control_plane,
            "project_field",
            return_value="",
        ),
        mock.patch.object(
            deploy_pipeline.control_plane,
            "seed_qa",
            return_value=0,
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
        mock.patch.object(deploy_pipeline.control_plane, "record_qa_stage"),
        mock.patch.object(
            deploy_pipeline.control_plane,
            "unresolved_qa",
            return_value=[],
        ),
    ):
        rc = deploy_pipeline.run_pipeline(
            run_id, from_stage="warm-up", sd="/tmp/sd"
        )

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
