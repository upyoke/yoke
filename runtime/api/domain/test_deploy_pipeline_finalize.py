"""Retry and pending-exit coverage for deploy-pipeline finalization."""

from __future__ import annotations

import json
import subprocess
from unittest import mock

import pytest

from yoke_core.domain import (
    deploy_pipeline,
    deploy_pipeline_gates,
    deploy_pipeline_run_context as run_context,
    deploy_pipeline_run_updates as run_updates,
    deploy_qa_recorder,
)


@pytest.fixture(autouse=True)
def holding_the_deploy_lock():
    """Run the pipeline as the session holding the project deploy lock.

    Executing a run is gated on that claim; these tests are about the
    stage machinery, and the gate has its own coverage.
    """
    with mock.patch.object(
        deploy_pipeline, "deploy_lock_refusal", return_value=None,
    ):
        yield

def test_run_update_uses_in_process_registered_mutation(monkeypatch):
    update = mock.Mock(return_value=None)
    spawn = mock.Mock(side_effect=AssertionError("must not spawn"))
    monkeypatch.setattr(
        run_updates.deployment_runs_crud_mutate,
        "cmd_update",
        update,
    )
    monkeypatch.setattr(subprocess, "run", spawn)

    run_updates.update_run_field("run-1", "status", "succeeded")

    update.assert_called_once_with("run-1", "status", "succeeded")
    spawn.assert_not_called()


def test_status_write_retries_then_lands(monkeypatch):
    sleeps: list[float] = []
    attempts = {"n": 0}

    def fake_update(run_id, field, value):
        assert (run_id, field, value) == ("run-1", "status", "succeeded")
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise run_updates.DeployPipelineRunUpdateError("write unavailable")

    monkeypatch.setattr(run_updates, "update_run_field", fake_update)
    monkeypatch.setattr(run_context.time, "sleep", sleeps.append)
    monkeypatch.setattr(run_context, "_emit_run_event", lambda *a, **k: None)

    run_context.finalize_run_success(
        "run-1",
        "flow",
        "yoke",
        [],
        "persistent",
        "stage",
    )

    assert attempts["n"] == 3
    assert sleeps == [1.0, 2.0]


def test_exhausted_status_retries_are_finalization_pending(monkeypatch):
    def fail(*_args):
        raise run_updates.DeployPipelineRunUpdateError("write unavailable")

    monkeypatch.setattr(run_updates, "update_run_field", fail)
    monkeypatch.setattr(run_context.time, "sleep", lambda *_: None)
    monkeypatch.setattr(run_context, "_emit_run_event", lambda *a, **k: None)

    with pytest.raises(run_context.RunFinalizationPending) as pending:
        run_context.finalize_run_success(
            "run-1",
            "flow",
            "yoke",
            [],
            "persistent",
            "stage",
        )

    assert pending.value.run_id == "run-1"
    assert "deploy succeeded, finalization pending" in str(pending.value)
    assert "re-drive run-1 to finalize" in str(pending.value)


def test_complete_run_finalization_returns_pending_exit(monkeypatch, capsys):
    update = mock.Mock(
        side_effect=run_updates.DeployPipelineRunUpdateError("write unavailable")
    )
    monkeypatch.setattr(run_updates, "update_run_field", update)
    monkeypatch.setattr(run_context.time, "sleep", lambda *_: None)

    rc = run_context.complete_run_finalization(
        "run-9",
        "flow",
        "yoke",
        [],
        "persistent",
        "stage",
    )

    assert rc == deploy_pipeline.EXIT_FINALIZATION_PENDING
    assert rc != deploy_pipeline.EXIT_STAGE_FAILED
    assert update.call_count == 3
    assert "re-drive run-9 to finalize" in capsys.readouterr().err


def _run_resumed(monkeypatch, *, status: str, stage: str, finish):
    run_id = "run-env-001"
    stages = json.dumps(
        [
            {"name": "merged", "step_runner": "auto"},
            {"name": "complete", "step_runner": "auto"},
        ]
    )

    def fake_yoke_db(*args, sd=None):
        if args[:2] == ("runs", "get"):
            return (
                f"{run_id}|yoke|flow-env|persistent|stage|{'d' * 40}|{status}|{stage}"
            )
        return ""

    def fake_flow_db(*args, sd=None):
        if args[0] == "stages":
            return stages
        if args[0] == "get":
            return "stage"
        return ""

    monkeypatch.setenv("YOKE_ENV", "prod")
    with (
        mock.patch.object(
            deploy_pipeline,
            "resolve_flow_gate_branch",
            return_value="stage",
        ),
        mock.patch.object(
            deploy_pipeline,
            "validate_itemless_product_source",
            return_value=mock.Mock(repo_path="/pinned/product", image_tag="abc"),
        ),
        mock.patch.object(
            deploy_pipeline,
            "_yoke_db",
            side_effect=fake_yoke_db,
        ),
        mock.patch.object(
            deploy_pipeline,
            "_flow_db",
            side_effect=fake_flow_db,
        ),
        mock.patch.object(
            deploy_pipeline,
            "_project_db",
            return_value="",
        ),
        mock.patch.object(
            deploy_pipeline,
            "resolve_project_checkout_path",
            return_value="/repo",
        ),
        mock.patch.object(
            deploy_pipeline,
            "resolve_flow_target",
            return_value=("persistent", "stage"),
        ),
        mock.patch.object(
            deploy_pipeline_gates,
            "_verify_branch_merged",
        ),
        mock.patch.object(
            deploy_pipeline,
            "_dispatch_step_runner",
            side_effect=AssertionError("stages must not re-run"),
        ),
        mock.patch.object(
            deploy_qa_recorder,
            "cmd_seed_from_flow",
            return_value=0,
        ),
        mock.patch.object(
            deploy_pipeline,
            "complete_run_finalization",
            finish,
        ),
    ):
        return deploy_pipeline.run_pipeline(
            run_id,
            product_repo_path="/pinned/product",
            image_tag="abc",
            sd="/tmp/sd",
        )


def test_complete_succeeded_does_not_re_finalize(monkeypatch):
    finish = mock.Mock(return_value=0)
    rc = _run_resumed(
        monkeypatch,
        status="succeeded",
        stage="complete",
        finish=finish,
    )
    assert rc == deploy_pipeline.EXIT_SUCCESS
    finish.assert_not_called()


def test_complete_not_succeeded_redrives_finalize(monkeypatch):
    finish = mock.Mock(return_value=deploy_pipeline.EXIT_FINALIZATION_PENDING)
    rc = _run_resumed(
        monkeypatch,
        status="executing",
        stage="complete",
        finish=finish,
    )
    assert rc == deploy_pipeline.EXIT_FINALIZATION_PENDING
    finish.assert_called_once()
