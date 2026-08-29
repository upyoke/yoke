"""Cursor model upgrade: a later measurement replaces a family id, not the reverse."""

from __future__ import annotations

import pytest

from runtime.api.test_sessions import _p, _register
from yoke_core.domain.sessions import SessionError

pytest_plugins = ("runtime.api.test_sessions",)


def test_register_does_not_replace_cursor_measurement_with_bare_family_id(conn) -> None:
    cursor = dict(executor="cursor-cli", provider="cursor")
    _register(conn, session_id="cursor-sess", model="cursor-grok-4.6-xhigh", **cursor)
    with pytest.raises(SessionError) as exc_info:
        _register(conn, session_id="cursor-sess", model="grok-4.6", **cursor)
    assert exc_info.value.code == "SESSION_EXISTS"

    row = conn.execute(
        f"SELECT model FROM harness_sessions WHERE session_id = {_p(conn)}",
        ("cursor-sess",),
    ).fetchone()
    assert row["model"] == "cursor-grok-4.6-xhigh"


def test_register_takes_a_later_cursor_variant_over_another_variant(conn) -> None:
    cursor = dict(executor="cursor-cli", provider="cursor")
    _register(
        conn, session_id="cursor-swap", model="cursor-grok-4.6-high-fast", **cursor
    )
    with pytest.raises(SessionError) as exc_info:
        _register(
            conn, session_id="cursor-swap", model="cursor-grok-4.6-xhigh", **cursor
        )
    assert exc_info.value.code == "SESSION_EXISTS"

    row = conn.execute(
        f"SELECT model FROM harness_sessions WHERE session_id = {_p(conn)}",
        ("cursor-swap",),
    ).fetchone()
    assert row["model"] == "cursor-grok-4.6-xhigh"
