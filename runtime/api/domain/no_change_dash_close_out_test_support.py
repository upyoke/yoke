# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_core.domain.handlers.lifecycle_transition import handle_transition

import json

from contextlib import contextmanager

from types import SimpleNamespace

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.session_holdings import insert_item_claim, insert_session

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain import (
    backlog_architecture_gate_runner,
    backlog_authoritative_status_gate,
    backlog_db_mutation_gate_runner,
    backlog_update_op,
    conflict_survey_gate,
    dash_evidence_gate,
    dash_posture_gate,
    db_helpers,
    deployment_flow_clearance as clearance,
    path_claims_gate_boundary,
    qa_gate_preconditions,
    qa_gates,
)

from yoke_core.domain.handlers.direct_workflow_execution import (
    handle_dash_evidence,
    handle_dash_survey,
)

from yoke_core.domain.qa_gate_definitions import GateTarget

from yoke_core.domain.qa_workflow_binding_validation import (
    optional_unattached_qa_permits_empty,
)

ITEM_ID = 7110

SESSION_ID = "no-change-close"


class _NonClosingConnection:
    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self):
        return None

    def __enter__(self):
        return self._connection

    def __exit__(self, *_exc):
        return None


def _bind_fixture_db(monkeypatch, test_db) -> None:
    def _connect(_path=None):
        return _NonClosingConnection(test_db)

    for module in (
        db_helpers,
        backlog_update_op,
        backlog_authoritative_status_gate,
        backlog_architecture_gate_runner,
        backlog_db_mutation_gate_runner,
        dash_evidence_gate,
        dash_posture_gate,
        path_claims_gate_boundary,
        qa_gate_preconditions,
        qa_gates,
        conflict_survey_gate,
    ):
        if hasattr(module, "connect"):
            monkeypatch.setattr(module, "connect", _connect)


def _request(
    function: str,
    payload: dict,
    *,
    actor_id: str,
    item_id: int = ITEM_ID,
    session_id: str = SESSION_ID,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=actor_id, session_id=session_id),
        target=TargetRef(kind="item", item_id=item_id, project_id="yoke"),
        payload=payload,
    )


def _empty_delivery_reads(monkeypatch) -> None:
    def _dispatch(*, function_id, **_kwargs):
        if function_id == "workflows.mechanics.get":
            return SimpleNamespace(
                success=True, result={"delivery_defaults": []}, error=None
            )
        if function_id == "done_transition.registered_flow_ids":
            return SimpleNamespace(success=True, result={"flow_ids": []}, error=None)
        raise AssertionError(function_id)

    monkeypatch.setattr(clearance, "call_dispatcher", _dispatch)
