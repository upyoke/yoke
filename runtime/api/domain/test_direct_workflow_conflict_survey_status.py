"""Transport-mode coverage for the recorded-survey status read.

Two proofs, one per connection mode:

* In-process: the ``direct_workflow.conflict_survey.status`` handler run
  directly against a seeded Postgres ``test_db`` returns the recorded
  survey plus a fresh conflict re-check (found / not-found / contacts).
  This is the local-Postgres in-process dispatch path.

* Relay routing: ``direct_workflow_worktree_preflight.run`` drives its
  control-plane reads through ``call_dispatcher`` (``items.detail.get``
  then ``direct_workflow.conflict_survey.status``) and rebuilds missing
  or incomplete survey refusals -- with no bare ``connect()`` on the hot
  path. Overlap-contact advisories live in
  ``test_conflict_survey_claim_advisory``.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import db_helpers
from yoke_core.domain import direct_workflow_worktree_preflight as preflight
from yoke_core.domain.conflict_survey import record_conflict_survey, survey_conflicts
from yoke_core.domain.handlers import direct_workflow_conflict_survey_status as status_mod
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.conflict_survey import (
    DURABLE_ABSENT,
    DURABLE_PENDING,
    DURABLE_RECORDED,
    DURABLE_UNREADABLE,
)


@pytest.fixture(autouse=True)
def _item_sections_contract(test_db):
    test_db.execute(
        "CREATE TABLE IF NOT EXISTS item_sections ("
        "item_id INTEGER NOT NULL REFERENCES items(id), "
        "section_name TEXT NOT NULL, content TEXT NOT NULL, "
        "ordering INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "PRIMARY KEY(item_id, section_name))"
    )
    test_db.commit()


def _status_request(item_id: int) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="direct_workflow.conflict_survey.status",
        actor=ActorContext(actor_id="op", session_id="s-status"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={},
    )


def _call_status(monkeypatch, test_db, item_id: int):
    @contextmanager
    def _use():
        yield test_db

    monkeypatch.setattr(db_helpers, "connect", _use)
    return status_mod.handle_conflict_survey_status(_status_request(item_id))


# ---------------------------------------------------------------------------
# In-process (local-Postgres) handler proofs
# ---------------------------------------------------------------------------


def test_status_reports_recorded_clear_survey(test_db, monkeypatch):
    insert_item(test_db, id=3201, workflow_id="dash", title="Clear change")
    recorded = survey_conflicts(
        test_db, item_id=3201, touch_paths=["src/isolated_change.py"],
    )
    assert recorded.clear is True
    record_conflict_survey(test_db, recorded)

    outcome = _call_status(monkeypatch, test_db, 3201)

    assert outcome.primary_success is True
    payload = outcome.result_payload
    assert payload["found"] is True
    assert payload["durable_state"] == DURABLE_RECORDED
    assert payload["clear"] is True
    assert payload["workflow_id"] == "dash"
    assert payload["touch_paths"] == ["src/isolated_change.py"]
    assert payload["integration_target"] == "main"
    assert payload["fingerprint"]
    assert payload["blockers"] == []


def test_status_reports_not_found_without_recorded_survey(test_db, monkeypatch):
    insert_item(test_db, id=3202, workflow_id="dash", title="No survey yet")

    outcome = _call_status(monkeypatch, test_db, 3202)

    assert outcome.primary_success is True
    payload = outcome.result_payload
    assert payload["found"] is False
    assert payload["durable_state"] == DURABLE_ABSENT
    assert payload["clear"] is False
    assert payload["workflow_id"] == "dash"
    assert payload["touch_paths"] == []
    assert payload["blockers"] == []


@pytest.mark.parametrize(("item_id", "content", "durable_state"), [
    (3205, '{"pending_request":"request"}', DURABLE_PENDING),
    (3206, "{", DURABLE_UNREADABLE),
])
def test_status_classifies_nonrecorded_durable_rows(
    test_db, monkeypatch, item_id, content, durable_state,
):
    insert_item(test_db, id=item_id, workflow_id="dash", title="Incomplete survey")
    test_db.execute(
        "INSERT INTO item_sections "
        "(item_id, section_name, content, source, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (item_id, "Conflict Survey", content, "direct-workflow", "now", "now"),
    )
    test_db.commit()

    outcome = _call_status(monkeypatch, test_db, item_id)

    assert outcome.primary_success is True
    assert outcome.result_payload["durable_state"] == durable_state
    assert outcome.result_payload["found"] is False


def test_status_reports_blocked_survey(test_db, monkeypatch):
    insert_item(test_db, id=3203, workflow_id="dash", title="Contended change")
    insert_item(
        test_db,
        id=3204,
        workflow_id="dash",
        title="Registered work",
        spec="## File Budget\n\n- `src/contended.py`\n",
    )
    recorded = survey_conflicts(
        test_db, item_id=3203, touch_paths=["src/contended.py"],
    )
    assert recorded.clear is False
    record_conflict_survey(test_db, recorded)

    outcome = _call_status(monkeypatch, test_db, 3203)

    payload = outcome.result_payload
    assert payload["found"] is True
    assert payload["clear"] is False
    assert any(
        blocker["kind"] == "frontier_scope" and blocker["owner_item_id"] == 3204
        for blocker in payload["blockers"]
    )


def test_status_rejects_non_item_target():
    request = FunctionCallRequest(
        function="direct_workflow.conflict_survey.status",
        actor=ActorContext(actor_id="op", session_id="s-x"),
        target=TargetRef(kind="global"),
        payload={},
    )
    outcome = status_mod.handle_conflict_survey_status(request)
    assert outcome.primary_success is False
    assert outcome.error.code == "invalid_target"


# ---------------------------------------------------------------------------
# Relay-routing proof on the preflight hot path (https transport shape)
# ---------------------------------------------------------------------------


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
                {"item": {"id": self.item_id, "workflow": {"id": self.workflow}}},
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
