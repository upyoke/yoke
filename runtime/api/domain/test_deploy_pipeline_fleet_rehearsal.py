"""Hosted release fleet rehearsal before workflow dispatch."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import deploy_pipeline_fleet_rehearsal as rehearsal
from yoke_core.domain import deploy_pipeline_step_runners
from yoke_core.domain import migration_preflight_receipt as receipt

_DIGEST = "a" * 64
_RELEASE_SHA = "b" * 40
_HISTORY = ("0001_first_entry", "0002_rewrite_rows")
_RUN = "20260101T000000Z"


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


def _dispatch(stage: dict, environment: str = "prod") -> tuple[int, str]:
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
        environment_name=environment,
        gate_branch="main",
        release_lineage=_RELEASE_SHA,
        sd=None,
    )


def _covered(*, entries: tuple[str, ...] = _HISTORY, shape: bool = True) -> dict:
    """The coverage leaves a passing rehearsal of this release leaves behind."""
    values = {receipt.entry_coverage_path(name): _RUN for name in entries}
    if shape:
        values[receipt.schema_shape_coverage_path(_DIGEST)] = _RUN
    return values


def _stable_commit(monkeypatch) -> None:
    """Everything a release commit contributes except its history entries."""
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


def _stable_release(monkeypatch) -> None:
    _stable_commit(monkeypatch)
    monkeypatch.setattr(
        rehearsal,
        "_release_history",
        lambda _project, _repository, _sha: (_HISTORY, ""),
    )


def test_uncovered_release_rehearses_records_then_dispatches(monkeypatch) -> None:
    _stable_release(monkeypatch)
    events: list[str] = []
    query_count = 0

    def coverage(_project, _environment, _history, _digest):
        nonlocal query_count
        query_count += 1
        events.append("query")
        return ({}, "") if query_count == 1 else (_covered(), "")

    def run_preflight(args: list[str]) -> int:
        events.append("rehearsal")
        assert args == [
            "prod",
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

    monkeypatch.setattr(rehearsal, "_coverage", coverage)
    monkeypatch.setattr(rehearsal, "_run_preflight", run_preflight)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        dispatch,
    )

    assert _dispatch(_stage()) == (0, "")
    assert events == ["query", "rehearsal", "query", "dispatch"]


def test_unrehearsed_data_only_entry_rehearses_though_the_shape_is_covered(
    monkeypatch,
) -> None:
    # A history entry that rewrites rows alters no table, column or index, so
    # the schema-shape digest is unchanged and already covered. That entry is
    # the one a rehearsal against copies of the live fleet exists to catch.
    _stable_release(monkeypatch)
    covered_before = _covered(entries=_HISTORY[:1])
    query_count = 0

    def coverage(_project, _environment, _history, _digest):
        nonlocal query_count
        query_count += 1
        return (covered_before, "") if query_count == 1 else (_covered(), "")

    run_preflight = mock.Mock(return_value=0)
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(rehearsal, "_coverage", coverage)
    monkeypatch.setattr(rehearsal, "_run_preflight", run_preflight)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        workflow,
    )

    assert not receipt.uncovered_schema_shape(_DIGEST, covered_before)
    assert _dispatch(_stage()) == (0, "")
    run_preflight.assert_called_once()
    workflow.assert_called_once()


def test_covered_release_skips_rehearsal_and_dispatches(monkeypatch) -> None:
    _stable_release(monkeypatch)
    run_preflight = mock.Mock(return_value=0)
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(rehearsal, "_coverage", lambda *_a: (_covered(), ""))
    monkeypatch.setattr(rehearsal, "_run_preflight", run_preflight)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        workflow,
    )

    assert _dispatch(_stage()) == (0, "")
    run_preflight.assert_not_called()
    workflow.assert_called_once()


def test_entry_covered_for_one_environment_rehearses_only_the_other(
    monkeypatch,
) -> None:
    # Coverage is per environment, so an entry rehearsed against prod's fleet
    # says nothing about stage's, and the environment that already has it must
    # not pay for the rehearsal the other one needs.
    _stable_release(monkeypatch)
    by_environment = {"prod": _covered(), "stage": _covered(entries=_HISTORY[:1])}
    rehearsed: list[str] = []

    def coverage(_project, environment, _history, _digest):
        name = receipt.target_environment_for_admin_env(environment)
        return (by_environment[name], "")

    def run_preflight(args: list[str]) -> int:
        rehearsed.append(args[0])
        by_environment["stage"] = _covered()
        return 0

    monkeypatch.setattr(rehearsal, "_coverage", coverage)
    monkeypatch.setattr(rehearsal, "_run_preflight", run_preflight)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        mock.Mock(return_value=(0, "")),
    )

    assert _dispatch(_stage(), environment="prod") == (0, "")
    assert _dispatch(_stage(), environment="stage") == (0, "")
    assert rehearsed == ["stage"]


def test_rehearsal_failure_stops_before_workflow_dispatch(monkeypatch) -> None:
    _stable_release(monkeypatch)
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(rehearsal, "_coverage", lambda *_a: ({}, ""))
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
    monkeypatch.setattr(rehearsal, "_coverage", lambda *_a: ({}, ""))
    monkeypatch.setattr(rehearsal, "_run_preflight", lambda _args: 0)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        workflow,
    )

    rc, diagnostic = _dispatch(_stage())

    assert rc == 1
    assert "receipt does not cover" in diagnostic
    assert _HISTORY[0] in diagnostic
    assert _DIGEST in diagnostic
    workflow.assert_not_called()


def test_other_workflows_do_not_enter_the_internal_rehearsal(monkeypatch) -> None:
    coverage = mock.Mock(side_effect=AssertionError("unexpected receipt read"))
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(rehearsal, "_coverage", coverage)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        workflow,
    )

    assert _dispatch(_stage(workflow="customer-release.yml")) == (0, "")
    coverage.assert_not_called()
    workflow.assert_called_once()


def test_unreadable_coverage_stops_dispatch_rather_than_rehearsing(
    monkeypatch,
) -> None:
    # Not knowing whether the release was rehearsed is not the same as knowing
    # it was not, and dispatching on an unanswered question is how an
    # unrehearsed entry reaches the fleet.
    _stable_release(monkeypatch)
    workflow = mock.Mock(return_value=(0, ""))
    run_preflight = mock.Mock(return_value=0)
    monkeypatch.setattr(
        rehearsal,
        "read_coverage",
        lambda **_kwargs: ({}, "permission_denied: items.read"),
    )
    monkeypatch.setattr(rehearsal, "_run_preflight", run_preflight)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        workflow,
    )

    rc, diagnostic = _dispatch(_stage())

    assert rc == 1
    assert "could not read fleet rehearsal receipts" in diagnostic
    assert "items.read" in diagnostic
    run_preflight.assert_not_called()
    workflow.assert_not_called()


def test_unresolvable_history_stops_dispatch_rather_than_rehearsing(
    monkeypatch,
) -> None:
    # A release whose entries cannot be enumerated would otherwise read as a
    # release carrying none, which is the silent pass this gate removes.
    _stable_commit(monkeypatch)
    monkeypatch.setattr(
        rehearsal,
        "_modules_dir",
        lambda _project: ("", "could not resolve the migration_model history"),
    )
    coverage = mock.Mock(side_effect=AssertionError("unexpected receipt read"))
    workflow = mock.Mock(return_value=(0, ""))
    run_preflight = mock.Mock(return_value=0)
    monkeypatch.setattr(rehearsal, "_coverage", coverage)
    monkeypatch.setattr(rehearsal, "_run_preflight", run_preflight)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        workflow,
    )

    rc, diagnostic = _dispatch(_stage())

    assert rc == 1
    assert "migration_model history" in diagnostic
    coverage.assert_not_called()
    run_preflight.assert_not_called()
    workflow.assert_not_called()


def test_coverage_is_read_for_the_environment_being_released(monkeypatch) -> None:
    _stable_release(monkeypatch)
    asked: list[dict] = []

    def read(**kwargs):
        asked.append(kwargs)
        return _covered(), ""

    monkeypatch.setattr(rehearsal, "read_coverage", read)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        mock.Mock(return_value=(0, "")),
    )

    assert _dispatch(_stage()) == (0, "")
    assert asked == [
        {
            "project": "yoke",
            "environment": "prod",
            "paths": receipt.coverage_paths(_HISTORY, _DIGEST),
        }
    ]
