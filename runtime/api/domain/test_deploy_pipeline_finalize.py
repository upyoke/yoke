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
    deploy_qa_recorder,
)
from yoke_core.domain.deploy_pipeline_reporting import (
    DeployPipelineCommandError,
)


def test_status_write_retries_then_lands(monkeypatch):
    sleeps: list[float] = []
    attempts = {"n": 0}

    def fake_yoke_db(*args, sd=None):
        if args[:4] == ("runs", "update", "run-1", "status"):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise subprocess.TimeoutExpired(cmd=list(args), timeout=60)
        return ""

    monkeypatch.setattr(run_context, "_yoke_db", fake_yoke_db)
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
    def fail(*args, sd=None):
        raise DeployPipelineCommandError("spawn timed out")

    monkeypatch.setattr(run_context, "_yoke_db", fail)
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
    monkeypatch.setattr(
        run_context,
        "finalize_run_success",
        mock.Mock(side_effect=run_context.RunFinalizationPending("run-9")),
    )

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
