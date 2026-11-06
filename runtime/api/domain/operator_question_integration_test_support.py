# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import importlib

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    _project,
    seed_session,
    _bodies,
    _recipients,
)

from runtime.api.domain.coordination_claim_test_support import PROJECT_YOKE

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers.decision_request_questions import handle_ask, handle_list

from yoke_core.domain.decision_request_resolution import resolve_decision_request

from yoke_core.domain.inbox_read import inbox_for_actor


def _call(function, session, payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="1", session_id=session),
        target=TargetRef(kind="global"),
        payload=payload,
    )
