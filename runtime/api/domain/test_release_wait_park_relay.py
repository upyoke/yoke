# ruff: noqa: F811
"""The park stamp reaches the real registered surfaces, not a stand-in.

``test_release_wait_park`` covers the decision logic against a fake
dispatcher, which cannot catch the failure that matters most here: a
payload, target kind, or function id the registered handler would refuse.
A park that is only ever exercised against a mock is a park that can be
silently unstamped in production while every test still passes — and an
unstamped wait is what the stale sweep reclaims.

So this one drives ``retain_for_delivery`` through the real handlers and
asserts the stored ``harness_sessions`` row, end to end.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from runtime.api.test_sessions import (  # noqa: F401
    _connect_with_backend_setup,
    _register,
    conn,
)
from yoke_core.domain import release_wait_park as park
from yoke_core.domain.handlers import sessions_orchestration
from yoke_core.domain.release_wait_ownership import HOLDER_FUNCTION, park_reason
from yoke_core.domain.session_mode import SESSION_MODE_PARKED

SESSION = "sess-1"


class _NullAuthority:
    def __enter__(self) -> "_NullAuthority":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


def _registered_dispatch(tmp_path, monkeypatch, *, holder: str):
    """Route the holder read to a fixture and the touch to its real handler.

    The handler owns the connection it is given and closes it, so it gets a
    fresh one per call; the test keeps its own to read the stored row back
    independently, which is the whole point of not mocking this.
    """
    monkeypatch.setattr(
        sessions_orchestration,
        "_connect_rw",
        lambda: _connect_with_backend_setup(tmp_path),
    )

    def dispatch(*, function_id, target, payload=None, actor=None, **_kw):
        if function_id == HOLDER_FUNCTION:
            found = {"session_id": holder} if holder else None
            return SimpleNamespace(
                success=True, result={"holder": found}, error=None
            )
        from yoke_contracts.api.function_call import (
            ActorContext,
            FunctionCallRequest,
        )

        outcome = sessions_orchestration.handle_touch(
            FunctionCallRequest(
                function=function_id,
                actor=ActorContext(actor_id="2", session_id=SESSION),
                target=target,
                payload=payload or {},
            )
        )
        return SimpleNamespace(
            success=outcome.primary_success,
            result=outcome.result_payload,
            error=outcome.error,
        )

    return dispatch


def _stored_mode(conn) -> tuple[str, str]:
    row = conn.execute(
        "SELECT mode, quiet_reason FROM harness_sessions WHERE session_id = %s",
        (SESSION,),
    ).fetchone()
    return str(row["mode"] or ""), str(row["quiet_reason"] or "")


def test_the_registered_touch_really_parks_the_owner(conn, tmp_path, monkeypatch):
    _register(conn, session_id=SESSION, mode="dash")
    monkeypatch.setattr(park, "connected_control_plane", lambda: _NullAuthority())
    monkeypatch.setattr(
        park,
        "call_dispatcher",
        _registered_dispatch(tmp_path, monkeypatch, holder=SESSION),
    )
    envelope: dict = {}

    park.retain_for_delivery(
        envelope, item_id=7, public_ref="ITEM-7", session_id=SESSION
    )

    assert envelope["release_wait"]["parked"] == "yes"
    assert _stored_mode(conn) == (SESSION_MODE_PARKED, park_reason("ITEM-7"))


def test_a_non_owner_leaves_the_stored_mode_alone(conn, tmp_path, monkeypatch):
    _register(conn, session_id=SESSION, mode="dash")
    monkeypatch.setattr(park, "connected_control_plane", lambda: _NullAuthority())
    monkeypatch.setattr(
        park,
        "call_dispatcher",
        _registered_dispatch(tmp_path, monkeypatch, holder="somebody-else"),
    )
    envelope: dict = {}

    park.retain_for_delivery(
        envelope, item_id=7, public_ref="ITEM-7", session_id=SESSION
    )

    assert envelope["release_wait"]["parked"].startswith("skipped:")
    assert _stored_mode(conn)[0] == "dash"
