# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from datetime import datetime, timedelta, timezone

from runtime.api.fixtures.backlog import insert_event

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain import hook_client_wall, hook_overhead

from yoke_core.domain.handlers import sessions_hook_overhead

from yoke_core.domain.observe_timing import PENDING_DELIVERY_WINDOW


class _KeepOpenConnection:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def close(self) -> None:
        pass


def _use_fixture_database(monkeypatch, test_db) -> None:
    connection = _KeepOpenConnection(test_db)
    monkeypatch.setattr(hook_client_wall.db_backend, "connect", lambda: connection)
    monkeypatch.setattr(hook_overhead.db_backend, "connect", lambda: connection)
    monkeypatch.setattr(
        hook_client_wall.db_backend, "connection_is_postgres", lambda _conn: True
    )


def _request(hours) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.hook_overhead",
        actor=ActorContext(session_id="hook-overhead-test"),
        target=TargetRef(kind="global"),
        payload={"hours": hours},
    )
