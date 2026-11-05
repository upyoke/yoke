# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import unittest

from yoke_core.domain.handlers import qa_requirement_create

from yoke_core.domain.qa_workflow_binding_validation import (
    item_transition_for_gate,
)

from yoke_core.domain.workflow_gate_catalog import GATE_QA_VERIFICATION

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.pg_testdb import test_database


def _request(function_id: str, item_id, payload) -> FunctionCallRequest:
    target = (
        TargetRef(kind="item", item_id=item_id)
        if item_id is not None
        else TargetRef(kind="global")
    )
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
        payload=payload,
    )
