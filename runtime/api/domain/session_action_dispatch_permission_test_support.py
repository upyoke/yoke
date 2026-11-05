# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import sqlite3

from yoke_contracts.api.function_call import FunctionCallRequest

from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE, PERM_PROJECT_ADMIN

from yoke_core.domain.session_action_dispatch_permission import (
    session_action_dispatch_permission,
    target_session_row,
)

from yoke_core.domain.yoke_function_registry import RegistryEntry

from runtime.api.domain.session_message_support_test_support import (
    NOW_TEXT,
    message_connection,
)


def _entry(function_id: str) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda request: None,
        request_model=FunctionCallRequest,
        response_model=FunctionCallRequest,
        stability="stable",
        owner_module="test",
        target_kinds=("global",),
        side_effects=("harness_sessions_update",),
        emitted_event_names=("YokeFunctionCalled",),
        guardrails=("verified_actor",),
        adapter_status="live",
    )


def _request(function_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest.model_validate(
        {
            "function": function_id,
            "actor": {"actor_id": "10", "session_id": "caller"},
            "target": {"kind": "global"},
            "payload": payload,
        }
    )
