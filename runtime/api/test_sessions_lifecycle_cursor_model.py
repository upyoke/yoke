"""Cursor served-model healing: a later attestation wins, nothing never clears."""

from __future__ import annotations

import pytest

from runtime.api.test_sessions import _p, _register
from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_core.domain.sessions import SessionError

pytest_plugins = ("runtime.api.test_sessions",)


def _stored_model(conn, session_id: str) -> str:
    row = conn.execute(
        f"SELECT model FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    return row["model"]


def test_a_registration_that_attests_nothing_keeps_the_stored_measurement(
    conn,
) -> None:
    """Cursor's store is silent until the conversation composes a request.

    Every later hook event re-registers, and most of them have nothing to
    attest. Letting those clear the column would erase the one measurement
    the run ever produced.
    """
    cursor = dict(executor="cursor-cli", provider="cursor")
    _register(
        conn,
        session_id="cursor-sess",
        model_facts=SessionModelFacts(model="cursor-grok-4.6-xhigh"),
        **cursor,
    )
    with pytest.raises(SessionError) as exc_info:
        _register(
            conn,
            session_id="cursor-sess",
            model_facts=SessionModelFacts(requested_model="grok-4.6"),
            **cursor,
        )
    assert exc_info.value.code == "SESSION_EXISTS"

    assert _stored_model(conn, "cursor-sess") == "cursor-grok-4.6-xhigh"


def test_register_takes_a_later_cursor_variant_over_another_variant(conn) -> None:
    """A conversation that switched variants is serving the later one."""
    cursor = dict(executor="cursor-cli", provider="cursor")
    _register(
        conn,
        session_id="cursor-swap",
        model_facts=SessionModelFacts(model="cursor-grok-4.6-high-fast"),
        **cursor,
    )
    with pytest.raises(SessionError) as exc_info:
        _register(
            conn,
            session_id="cursor-swap",
            model_facts=SessionModelFacts(model="cursor-grok-4.6-xhigh"),
            **cursor,
        )
    assert exc_info.value.code == "SESSION_EXISTS"

    assert _stored_model(conn, "cursor-swap") == "cursor-grok-4.6-xhigh"
