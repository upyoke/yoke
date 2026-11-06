# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from unittest.mock import patch

import pytest

from yoke_core.domain import db_backend

from yoke_core.domain.db_helpers import connect

from yoke_core.domain.events import EmitResult

from yoke_core.domain.handlers import ouroboros_field_note as _ofn

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from runtime.api.fixtures.dispatch_actor import register_session_actor

from runtime.api.fixtures.file_test_db import init_test_db


def _build_request(
    *,
    kind: str = "observation",
    evidence: str = "observation: stale doc reference noticed",
    correlation_id: str | None = None,
    target_kind: str = "global",
    session_id: str = "session-test-1",
    actor_id: str | None = None,
) -> FunctionCallRequest:
    payload: dict = {
        "yoke_version": "0.2.0.202610290013",
        "agent": "terminal",
        "category": kind,
        "evidence": evidence,
    }
    if correlation_id is not None:
        payload["correlation_id"] = correlation_id
    actor_kwargs: dict = {"session_id": session_id}
    if actor_id is not None:
        actor_kwargs["actor_id"] = actor_id
    return FunctionCallRequest(
        function="ouroboros.field_note.append",
        actor=ActorContext(**actor_kwargs),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


def _ok_emit_result(event_id: str = "evt-test-1") -> EmitResult:
    return EmitResult(ok=True, event_id=event_id, reason="", envelope=None)
