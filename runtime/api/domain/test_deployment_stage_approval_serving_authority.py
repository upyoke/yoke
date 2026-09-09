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


def test_an_admin_connection_routes_to_the_plane_it_administers(monkeypatch):
    """A database door is not a plane; its https sibling is."""
    from yoke_cli.transport import https as https_transport

    monkeypatch.setattr(
        https_transport,
        "resolve_https_connection",
        lambda *a, **k: None,
    )
    from yoke_cli.config import machine_config

    monkeypatch.setattr(
        machine_config,
        "active_env",
        lambda *a, **k: "prod-db-admin",
    )
    monkeypatch.setattr(
        machine_config,
        "load_config",
        lambda *a, **k: {
            "connections": {
                "prod": {"transport": "https", "api_url": "https://example"},
                "prod-db-admin": {"transport": "local-postgres"},
            }
        },
    )
    assert control_plane_transport.serving_control_plane_env() == "prod"


def test_a_local_universe_serves_itself(monkeypatch):
    from yoke_cli.transport import https as https_transport
    from yoke_cli.config import machine_config

    monkeypatch.setattr(
        https_transport,
        "resolve_https_connection",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(machine_config, "active_env", lambda *a, **k: "local")
    monkeypatch.setattr(
        machine_config,
        "load_config",
        lambda *a, **k: {"connections": {"local": {"transport": "local-postgres"}}},
    )
    assert control_plane_transport.serving_control_plane_env() == ""


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
