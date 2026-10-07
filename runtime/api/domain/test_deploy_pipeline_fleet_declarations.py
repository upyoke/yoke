"""Each project's declared migration-model fleet decides its release gate."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import deploy_pipeline_fleet_rehearsal as rehearsal
from yoke_core.domain import deploy_pipeline_step_runners
from runtime.api.domain.fleet_rehearsal_dispatch_test_helpers import (
    _covered,
    _declare,
    _dispatch,
    _model,
    _stable_release,
    _stage,
)


def _unexpected_coverage(monkeypatch) -> mock.Mock:
    coverage = mock.Mock(side_effect=AssertionError("unexpected receipt read"))
    monkeypatch.setattr(rehearsal, "_coverage", coverage)
    return coverage


def test_project_without_a_migration_model_dispatches_unread(monkeypatch) -> None:
    _declare(monkeypatch, {})
    coverage = _unexpected_coverage(monkeypatch)
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(
        deploy_pipeline_step_runners, "_dispatch_github_actions_workflow", workflow
    )

    assert _dispatch(_stage(workflow="customer-release.yml")) == (0, "")
    coverage.assert_not_called()
    workflow.assert_called_once()


def test_model_declaring_no_fleet_dispatches_with_its_reason(
    monkeypatch, capsys
) -> None:
    reason = "single SQLite database on the production host"
    _declare(monkeypatch, {"primary": _model({"kind": "none", "reason": reason})})
    coverage = _unexpected_coverage(monkeypatch)
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(
        deploy_pipeline_step_runners, "_dispatch_github_actions_workflow", workflow
    )

    assert _dispatch(_stage(), project="buzz") == (0, "")
    assert reason in capsys.readouterr().out
    coverage.assert_not_called()
    workflow.assert_called_once()


def test_model_with_undeclared_fleet_refuses_with_the_declaration_recipe(
    monkeypatch,
) -> None:
    _declare(monkeypatch, {"registry": _model(None)})
    coverage = _unexpected_coverage(monkeypatch)
    workflow = mock.Mock(return_value=(0, ""))
    monkeypatch.setattr(
        deploy_pipeline_step_runners, "_dispatch_github_actions_workflow", workflow
    )

    rc, diagnostic = _dispatch(_stage(), project="platform")

    assert rc == 1
    assert "declares no fleet" in diagnostic
    assert "--project platform --cap-type migration_fleet" in diagnostic
    coverage.assert_not_called()
    workflow.assert_not_called()


def test_named_database_fleet_rehearses_its_own_project_and_model(
    monkeypatch,
) -> None:
    named = _model(
        {
            "kind": "named_databases",
            "names": ["yoke_platform"],
            "converge_argv": ["python", "-m", "service.schema", "init"],
            "schema_shape_sources": ["service/schema.py"],
        }
    )
    _stable_release(monkeypatch, {"registry": named})
    asked: list[str] = []
    rehearsed: list[list[str]] = []

    def coverage(project, _model, _environment, _history, _digest):
        asked.append(project)
        return ({}, "") if not rehearsed else (_covered(model="registry"), "")

    def run_preflight(args: list[str]) -> int:
        rehearsed.append(args)
        return 0

    monkeypatch.setattr(rehearsal, "_coverage", coverage)
    monkeypatch.setattr(rehearsal, "_run_preflight", run_preflight)
    monkeypatch.setattr(
        deploy_pipeline_step_runners,
        "_dispatch_github_actions_workflow",
        mock.Mock(return_value=(0, "")),
    )

    assert _dispatch(_stage(), environment="stage", project="platform") == (0, "")
    assert asked == ["platform", "platform"]
    assert rehearsed[0][:7] == [
        "--checkout",
        "/release-checkout",
        "--project",
        "platform",
        "--model",
        "registry",
        "stage",
    ]
