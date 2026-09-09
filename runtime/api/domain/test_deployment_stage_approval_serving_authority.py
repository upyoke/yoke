"""The deploy driver asks the serving build for its approval verdict.

A release driver runs the candidate revision while the control plane it
reads still runs the deployed one. Deriving the verdict locally reads the
candidate's columns out of the deployed build's database, so a release that
adds or retires a column crashes its own approval gate. These tests hold the
driver to asking instead of computing.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import control_plane_transport
from yoke_core.domain import deployment_stage_approval_dispatch as dispatch
from runtime.api.domain.test_serving_control_plane_env import (
    stub_machine_connections,
)
from yoke_core.domain.deployment_approval_requests import (
    EVALUATE_STAGE_APPROVAL_FUNCTION,
)


class _RecordedCall:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple] = []

    def __call__(self, function_id, payload, target=None):
        self.calls.append((function_id, payload, target))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _dispatch_with(
    monkeypatch, result, *, run_id="run-serving-1", stage="approve-prod"
):
    recorder = _RecordedCall(result)
    monkeypatch.setattr(dispatch, "serving_authority", recorder, raising=False)
    monkeypatch.setattr(
        control_plane_transport,
        "serving_authority",
        recorder,
    )
    return recorder, dispatch.dispatch_deployment_stage_approval(run_id, stage)


def test_pending_verdict_suspends_the_pipeline_at_this_exact_stage(
    monkeypatch,
    capsys,
):
    recorder, outcome = _dispatch_with(
        monkeypatch,
        {
            "satisfied": False,
            "request_id": 77,
            "request_status": "pending",
            "resolution_action": None,
            "reason": "waiting",
        },
    )
    assert outcome == (-2, "")
    function_id, payload, target = recorder.calls[0]
    assert function_id == EVALUATE_STAGE_APPROVAL_FUNCTION
    assert payload == {"stage": "approve-prod"}
    assert target.kind == "workflow_run"
    assert target.workflow_run_id == "run-serving-1"
    assert "77" in capsys.readouterr().out


def test_resolved_approval_lets_the_stage_pass(monkeypatch):
    _, outcome = _dispatch_with(
        monkeypatch,
        {
            "satisfied": True,
            "request_id": 78,
            "request_status": "resolved",
            "resolution_action": "approve",
            "reason": "resolved",
        },
    )
    assert outcome == (0, "")


def test_rejection_fails_the_stage_and_names_its_decision(monkeypatch):
    _, outcome = _dispatch_with(
        monkeypatch,
        {
            "satisfied": False,
            "request_id": 79,
            "request_status": "resolved",
            "resolution_action": "reject",
            "reason": "rejected",
        },
    )
    code, diagnostic = outcome
    assert code == 1
    assert "79" in diagnostic
    assert "rejected" in diagnostic


def test_an_unreachable_serving_plane_is_a_named_failure(monkeypatch):
    _, outcome = _dispatch_with(
        monkeypatch,
        RuntimeError("relay refused: no route"),
    )
    code, diagnostic = outcome
    assert code == 1
    assert "serving control plane" in diagnostic
    assert "no route" in diagnostic


def test_the_driver_never_opens_the_control_plane_database_itself(monkeypatch):
    """The schema the driver was built for is not the schema it is reading.

    A driver that opens the database is a driver whose own columns must
    match it, which is exactly the affinity this routing removes. Fail the
    local connection outright: the verdict must still arrive.
    """
    import yoke_core.domain.db_helpers as db_helpers

    def _refuse():
        raise AssertionError("the driver opened the serving database")

    monkeypatch.setattr(db_helpers, "connect", _refuse)
    _, outcome = _dispatch_with(
        monkeypatch,
        {
            "satisfied": True,
            "request_id": 80,
            "request_status": "resolved",
            "resolution_action": "approve",
            "reason": "resolved",
        },
    )
    assert outcome == (0, "")


def test_that_refusal_reaches_the_pipeline_as_a_named_stage_failure(monkeypatch):
    stub_machine_connections(
        monkeypatch,
        active="stage-db-admin",
        connections={"stage-db-admin": {"transport": "local-postgres"}},
    )
    code, diagnostic = dispatch.dispatch_deployment_stage_approval(
        "run-serving-2", "approve-prod"
    )
    assert code == 1
    assert "serving control plane" in diagnostic
    assert "stage-db-admin" in diagnostic


def test_the_public_cli_evaluation_routes_to_the_serving_plane(monkeypatch):
    """The operator command makes the same promise the pipeline does.

    Under an admin connection an ordinary dispatch runs in-process, which
    would evaluate with the caller's revision against the deployed build's
    database — the exact defect, reached through the public command.
    """
    from yoke_cli.commands import _helpers
    from yoke_cli.commands.adapters import deployment_stage_approval as adapter

    stub_machine_connections(
        monkeypatch,
        active="prod-db-admin",
        connections={
            "prod": {"transport": "https", "api_url": "https://example"},
            "prod-db-admin": {"transport": "local-postgres"},
        },
    )
    seen: dict = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(_helpers, "dispatch_and_emit", _capture)
    monkeypatch.setattr(adapter, "dispatch_and_emit", _capture, raising=False)
    assert (
        adapter.deployment_runs_stage_approval_evaluate(
            ["run-serving-3", "--stage", "approve-prod"]
        )
        == 0
    )
    assert seen["relay_env"] == "prod"
    assert seen["function_id"] == EVALUATE_STAGE_APPROVAL_FUNCTION
    assert seen["payload"] == {"stage": "approve-prod"}


def test_the_public_cli_refuses_when_the_serving_plane_cannot_be_named(
    monkeypatch, capsys
):
    from yoke_cli.commands.adapters import deployment_stage_approval as adapter

    stub_machine_connections(
        monkeypatch,
        active="prod-db-admin",
        connections={"prod-db-admin": {"transport": "local-postgres"}},
    )

    def _must_not_dispatch(**_kwargs):
        raise AssertionError("the command dispatched without a serving plane")

    monkeypatch.setattr(adapter, "dispatch_and_emit", _must_not_dispatch, raising=False)
    exit_code = adapter.deployment_runs_stage_approval_evaluate(
        ["run-serving-4", "--stage", "approve-prod", "--json"]
    )
    assert exit_code == 1
    assert "serving_control_plane_unresolved" in capsys.readouterr().out


def test_a_named_plane_that_resolves_to_nothing_is_refused(monkeypatch):
    """Naming a plane and silently running here instead is the whole defect."""
    from yoke_cli.transport import dispatcher as transport_dispatcher
    from yoke_cli.transport import https as https_transport
    from yoke_contracts.api.function_call import TargetRef

    monkeypatch.setattr(
        https_transport,
        "resolve_https_connection",
        lambda *a, **k: None,
    )
    response = transport_dispatcher.call_dispatcher(
        function_id=EVALUATE_STAGE_APPROVAL_FUNCTION,
        target=TargetRef(kind="workflow_run", workflow_run_id="run-x"),
        payload={"stage": "approve-prod"},
        relay_env="prod",
        _local_dispatch=lambda request: pytest.fail(
            "a named plane must not fall back to local dispatch"
        ),
    )
    assert response.success is False
    assert response.error.code == "relay_env_unavailable"
    assert "prod" in response.error.message


def test_the_operator_adapter_is_reachable_from_the_cli():
    """A registered operation nobody can invoke is not yet an operation."""
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY, resolve

    route = ("deployment-runs", "stage-approval", "evaluate")
    assert route in SUBCOMMAND_REGISTRY
    assert SUBCOMMAND_REGISTRY[route][0] == EVALUATE_STAGE_APPROVAL_FUNCTION
    resolved_route, function_id, _adapter, rest = resolve(
        ["deployment-runs", "stage-approval", "evaluate", "run-x", "--stage", "s"]
    )
    assert resolved_route == route
    assert function_id == EVALUATE_STAGE_APPROVAL_FUNCTION
    assert rest == ["run-x", "--stage", "s"]
