"""A malformed launch id is not an absent launch."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.session_launch_validation import require_launch_id
from runtime.api.domain.session_launch_test_support import (
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


def _wire(monkeypatch, conn) -> None:
    monkeypatch.setattr(handlers, "_open", lambda: _NoCloseConnection(conn))
    monkeypatch.setattr(
        handlers,
        "_authorization",
        lambda _conn, _request, _project_id: authorization(operator=True),
    )


FRAGMENT = "46085585"


def _request(launch_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="session_control.launch.get",
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="global"),
        payload={"launch_id": launch_id},
    )


def test_a_short_hex_string_is_not_a_missing_launch() -> None:
    with pytest.raises(SessionLaunchError) as raised:
        require_launch_id(FRAGMENT)

    assert raised.value.code == "launch_id_invalid"
    assert FRAGMENT in str(raised.value)
    assert "not found" not in str(raised.value)
    assert "UUID" in str(raised.value)
    assert "8-4-4-4-12" in str(raised.value)


def test_get_launch_refuses_a_malformed_id_before_looking_up_a_row() -> None:
    conn = launch_connection()

    with pytest.raises(SessionLaunchError) as raised:
        get_launch(conn, FRAGMENT)

    assert raised.value.code == "launch_id_invalid"
    assert "not found" not in str(raised.value)


def test_launch_get_teaches_the_uuid_shape_for_a_malformed_id(monkeypatch) -> None:
    conn = launch_connection()
    _wire(monkeypatch, conn)

    outcome = handlers.handle_launch_get(_request(FRAGMENT))

    assert not outcome.primary_success
    assert outcome.error.code == "launch_id_invalid"
    assert FRAGMENT in outcome.error.message
    assert "not found" not in outcome.error.message
    assert "UUID" in outcome.error.message
