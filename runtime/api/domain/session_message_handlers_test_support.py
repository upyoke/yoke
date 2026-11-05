# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import sqlite3

from yoke_contracts.api.function_call import FunctionCallRequest

from yoke_contracts.session_control.teaching import FLEET_OWNERSHIP_GUIDANCE

from yoke_core.domain.handlers import session_messages

from yoke_core.domain.handlers import session_messages_receipts

from yoke_core.domain.session_message_service import send_message

from runtime.api.domain.session_message_support_test_support import (
    NOW,
    message_connection,
    pin_message_clocks,
    selector,
)


def _request(
    function: str,
    payload: dict,
    *,
    actor_id: str | None = "10",
    session_id: str = "s1",
    target_kind: str = "global",
    options: dict | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest.model_validate(
        {
            "function": function,
            "actor": {"actor_id": actor_id, "session_id": session_id},
            "target": {"kind": target_kind},
            "payload": payload,
            "options": options or {},
        }
    )
