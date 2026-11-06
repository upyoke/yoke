# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers import session_launch as handlers

from yoke_core.domain.session_launch_store import get_launch

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)


class _NoCloseConnection:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        pass


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _wire_handler(monkeypatch, conn) -> None:
    monkeypatch.setattr(handlers, "_open", lambda: _NoCloseConnection(conn))
    monkeypatch.setattr(handlers, "_resolve_project", lambda _conn, _project: 10)
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_requests.utc_now",
        lambda: parse_instant(NOW),
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_surface_selection.utc_now",
        lambda: parse_instant(NOW),
    )
    monkeypatch.setattr(
        handlers,
        "launch_authorization",
        lambda _conn, _request, _project_id: authorization(),
    )
