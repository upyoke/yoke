# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import importlib

from unittest.mock import patch

import pytest

from runtime.api.domain.session_message_support_test_support import message_connection

from yoke_contracts.api.function_call import FunctionCallRequest

from yoke_contracts.session_queue_posture import SESSION_MODES

from yoke_core.domain.handlers.__init_register__ import register_all_handlers

from yoke_core.domain.session_steering_authority import (
    require_steering_authority,
)

from yoke_core.domain.sessions_analytics import SessionError

from yoke_core.domain.yoke_function_dispatch_claims import verify_claim

from yoke_core.domain.yoke_function_registry import lookup


def seat(conn, *, project=1, document=None):
    import json

    scope = {"project_id": project}
    if document:
        scope["document"] = document
    conn.execute(
        "INSERT INTO work_claims(session_id,target_kind,scope,claimed_at) "
        "VALUES ('s1','steering',?,'2026-01-01T00:00:00Z')",
        (json.dumps(scope),),
    )
