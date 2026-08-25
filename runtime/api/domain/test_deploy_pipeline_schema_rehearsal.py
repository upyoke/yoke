"""Hosted release schema rehearsal before workflow dispatch."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import deploy_pipeline_schema_rehearsal as rehearsal
from yoke_core.domain import deploy_pipeline_step_runners
from yoke_core.domain import migration_preflight_receipt as receipt

_DIGEST = "a" * 64
_RELEASE_SHA = "b" * 40


def _stage(
    *,
    name: str = rehearsal.HOSTED_RELEASE_STAGE,
    workflow: str = rehearsal.HOSTED_RELEASE_WORKFLOW,
) -> dict:
    config = {
        "name": name,
        "step_runner": "github-actions-workflow",
        "workflow": workflow,
    }
    return {"name": name, "step_runner": "github-actions-workflow", "config": config}


def _dispatch(stage: dict) -> tuple[int, str]:
    return deploy_pipeline_step_runners._dispatch_step_runner(
        stage,
        run_id="run-1",
        member_items=["1"],
        github_repo="upyoke/yoke",
        project="yoke",
        project_repo_path="/repo",
        branch="main",
        first_item="1",
        timeout_min=1,
        fresh=False,
        environment_name="prod",
        gate_branch="main",
        release_lineage=_RELEASE_SHA,
        sd=None,
    )


def _row() -> dict:
    return {
        "envelope": {
            "context": {
                receipt.ENVIRONMENT_KEY: "prod",
                receipt.SCHEMA_SHAPE_DIGEST_KEY: _DIGEST,
            }
        }
    }


def _stable_release(monkeypatch) -> None:
    monkeypatch.setattr(
        rehearsal,
        "_release_sha",
        lambda _lineage, _repository: (_RELEASE_SHA, ""),
    )
    monkeypatch.setattr(
        rehearsal,
        "digest_schema_shape_commit",
        lambda _repository, _sha: _DIGEST,
    )
    monkeypatch.setattr(
        rehearsal.deploy_pipeline_environment,
        "release_control_plane_env",
        lambda: "prod",
    )


def test_uncovered_digest_rehearses_records_then_dispatches(monkeypatch) -> None:
    _stable_release(monkeypatch)
    events: list[str] = []
    query_count = 0

    def rows(_project: str):
        nonlocal query_count
        query_count += 1
        events.append("query")
        return ([], "") if query_count == 1 else ([_row()], "")

    def run_preflight(args: list[str]) -> int:
        events.append("rehearsal")
        assert args == [
            "prod-db-admin",
            "--record-receipt",
            "--product-sha",
            _RELEASE_SHA,
            "--receipt-env",
            "prod",
        ]
        return 0

    def dispatch(_config, **_kwargs):
        events.append("dispatch")
        return 0, ""

    monkeypatch.setattr(rehearsal, "_receipt_rows", rows)
    monkeypatch.setattr(rehearsal, "_run_preflight", run_preflight)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        dispatch,
    )

    assert _dispatch(_stage()) == (0, "")
    assert events == ["query", "rehearsal", "query", "dispatch"]


def test_covered_digest_skips_rehearsal_and_dispatches(monkeypatch) -> None:
    _stable_release(monkeypatch)
    run_preflight = mock.Mock(return_value=0)
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(rehearsal, "_receipt_rows", lambda _project: ([_row()], ""))
    monkeypatch.setattr(rehearsal, "_run_preflight", run_preflight)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        workflow,
    )

    assert _dispatch(_stage()) == (0, "")
    run_preflight.assert_not_called()
    workflow.assert_called_once()


def test_rehearsal_failure_stops_before_workflow_dispatch(monkeypatch) -> None:
    _stable_release(monkeypatch)
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(rehearsal, "_receipt_rows", lambda _project: ([], ""))
    monkeypatch.setattr(rehearsal, "_run_preflight", lambda _args: 7)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        workflow,
    )

    rc, diagnostic = _dispatch(_stage())

    assert rc == 7
    assert "before dispatch" in diagnostic
    workflow.assert_not_called()


def test_passing_rehearsal_without_covering_receipt_stops_dispatch(
    monkeypatch,
) -> None:
    _stable_release(monkeypatch)
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(rehearsal, "_receipt_rows", lambda _project: ([], ""))
    monkeypatch.setattr(rehearsal, "_run_preflight", lambda _args: 0)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        workflow,
    )

    rc, diagnostic = _dispatch(_stage())

    assert rc == 1
    assert "receipt does not cover release schema shape" in diagnostic
    workflow.assert_not_called()


def test_other_workflows_do_not_enter_the_internal_rehearsal(monkeypatch) -> None:
    receipt_rows = mock.Mock(side_effect=AssertionError("unexpected receipt read"))
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(rehearsal, "_receipt_rows", receipt_rows)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        workflow,
    )

    assert _dispatch(_stage(workflow="customer-release.yml")) == (0, "")
    receipt_rows.assert_not_called()
    workflow.assert_called_once()
