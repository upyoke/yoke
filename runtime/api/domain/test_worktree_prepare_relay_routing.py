"""Preparation drives its control-plane reads through the dispatcher.

``direct_workflow_worktree_preflight.run`` reads the item and the recorded
survey over ``call_dispatcher`` — the https transport shape, where there is
no local database to connect to — and rebuilds a missing or incomplete
survey refusal from what it read. A bare ``connect()`` on this hot path is
the regression these tests exist to catch.

The in-process proof of the same status read lives in
``test_direct_workflow_conflict_survey_status``.
"""

from __future__ import annotations

import json

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_contracts.conflict_survey import DURABLE_PENDING, DURABLE_UNREADABLE
from yoke_core.domain import direct_workflow_worktree_preflight as preflight


def _resp(function: str, result: dict, *, success: bool = True) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=success,
        function=function,
        version="v1",
        result=result,
        error=None if success else FunctionError(code="x", message="boom"),
    )


class _RoutedDispatcher:
    """Canned ``call_dispatcher`` capturing the routed function ids."""

    def __init__(self, *, item_id: int, workflow: str, status_result: dict):
        self.item_id = item_id
        self.workflow = workflow
        self.status_result = status_result
        self.calls: list[dict] = []

    def __call__(self, *, function_id: str, target, **_kwargs):
        self.calls.append({"function_id": function_id, "target": target})
        if function_id == "items.detail.get":
            return _resp(
                function_id,
                {
                    "item": {
                        "id": self.item_id,
                        "workflow": {"id": self.workflow},
                        "project": {"id": 1, "slug": "yoke"},
                    }
                },
            )
        if function_id == "direct_workflow.conflict_survey.status":
            return _resp(function_id, self.status_result)
        raise AssertionError(f"unexpected function id {function_id!r}")

    @property
    def routed_ids(self) -> list[str]:
        return [call["function_id"] for call in self.calls]


def _install_relay(monkeypatch, dispatcher: _RoutedDispatcher) -> list[dict]:
    """Route call_dispatcher through *dispatcher*; forbid a bare connect."""
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        dispatcher,
    )

    def _no_connect(*_a, **_k):
        raise AssertionError("run() must not open a local connection")

    # The module no longer imports ``connect`` (all control-plane reads
    # route through the dispatcher); keep the guard defensive so a future
    # reintroduction is still caught, without requiring the symbol today.
    monkeypatch.setattr(preflight, "connect", _no_connect, raising=False)

    preflight_calls: list[dict] = []

    def _fake_run_preflight(**kwargs):
        preflight_calls.append(kwargs)
        return type("Outcome", (), {"ok": True, "to_envelope": lambda self: {}})()

    monkeypatch.setattr(preflight, "run_preflight", _fake_run_preflight)
    # The receipt's lane orientation does its own declaration reads, which
    # this test is not about; its composition has its own coverage.
    monkeypatch.setattr(
        preflight, "lane_orientation", lambda *_a, **_k: {},
    )
    return preflight_calls


def test_run_routes_clear_survey_through_dispatcher(monkeypatch):
    dispatcher = _RoutedDispatcher(
        item_id=4101,
        workflow="dash",
        status_result={
            "found": True,
            "clear": True,
            "touch_paths": ["src/isolated.py"],
            "integration_target": "main",
            "blockers": [],
        },
    )
    preflight_calls = _install_relay(monkeypatch, dispatcher)

    rc = preflight.run(["YOK-4101", "--workflow", "dash"])

    assert rc == 0
    assert dispatcher.routed_ids == [
        "items.detail.get",
        "direct_workflow.conflict_survey.status",
    ]
    assert len(preflight_calls) == 1
    assert preflight_calls[0]["item_id"] == 4101
    # The dash claim preparer carries the survey's touch paths forward.
    preparer = preflight_calls[0]["prepare_path_claims"]
    assert preparer.keywords["touch_paths"] == ("src/isolated.py",)
    assert preparer.keywords["integration_target"] == "main"


def test_run_rebuilds_missing_block_outcome(monkeypatch, capsys):
    dispatcher = _RoutedDispatcher(
        item_id=4102, workflow="dash", status_result={"found": False},
    )
    preflight_calls = _install_relay(monkeypatch, dispatcher)

    rc = preflight.run(["YOK-4102", "--workflow", "dash"])

    assert rc == 1
    assert preflight_calls == []
    emitted = json.loads(capsys.readouterr().out.strip())
    assert emitted["block_kind"] == "conflict-survey-missing"
    assert emitted["item_id"] == 4102


@pytest.mark.parametrize(
    "durable_state", [DURABLE_PENDING, DURABLE_UNREADABLE],
)
def test_run_blocks_incomplete_durable_state(monkeypatch, capsys, durable_state):
    dispatcher = _RoutedDispatcher(
        item_id=4105,
        workflow="dash",
        status_result={"found": False, "durable_state": durable_state},
    )
    preflight_calls = _install_relay(monkeypatch, dispatcher)

    assert preflight.run(["YOK-4105", "--workflow", "dash"]) == 1
    assert preflight_calls == []
    emitted = json.loads(capsys.readouterr().out.strip())
    assert emitted["block_kind"] == f"conflict-survey-{durable_state}"


def test_run_errors_on_workflow_mismatch(monkeypatch):
    dispatcher = _RoutedDispatcher(
        item_id=4104, workflow="issue", status_result={"found": True, "clear": True},
    )
    _install_relay(monkeypatch, dispatcher)

    with pytest.raises(SystemExit):
        preflight.run(["YOK-4104", "--workflow", "dash"])

    # The mismatch is caught after items.detail.get, before the survey read.
    assert dispatcher.routed_ids == ["items.detail.get"]
