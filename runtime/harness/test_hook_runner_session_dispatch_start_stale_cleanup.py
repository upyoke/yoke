# ruff: noqa: F811
"""SessionStart stale-session reap on the client-side dispatch path.

The relayed half has always run the shared janitor on SessionStart. The local
half registered and oriented the starting session without ever running it, so
on a machine whose control plane is a local Postgres nothing swept: a claimless
session stayed active hours past its eligibility until an operator swept by
hand. These cover the wiring (every harness family, after registration), the
transport boundary (no local authority sweeps nothing and fails nothing), and
the sweep's own outcome against a fixture database.
"""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.sessions_api_stale_test_helpers import _ago_minutes
from runtime.api.test_sessions import (
    _insert_claimable_items,
    _register,
    conn,  # noqa: F401
)
from yoke_core.domain.sessions import claim_work
from yoke_core.hooks import session_dispatch
from yoke_core.hooks import session_start_stale_cleanup as _reap
from yoke_core.hooks.types import HookContext


class _FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _KeepOpenConn:
    """Forward everything to the fixture connection but ignore ``close()``.

    The reap closes the connection it opened; the fixture owns this one and
    the assertions run after the sweep.
    """

    def __init__(self, inner) -> None:
        self._conn = inner

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        return None


def _session_start(executor_family: str) -> HookContext:
    return HookContext(
        event_name="SessionStart",
        executor_family=executor_family,
        executor_surface=executor_family,
        session_id="sess-start",
        payload={"session_id": "sess-start"},
    )


@pytest.fixture
def _quiet_start():
    """Neutralize the non-reap SessionStart side effects."""
    with mock.patch(
        "yoke_core.hooks.session_dispatch._root_and_db",
        return_value=("/Users/x/yoke", "/Users/x/yoke/data/yoke.db"),
    ), mock.patch(
        "yoke_core.hooks.session_dispatch._is_yoke_target", return_value=True,
    ), mock.patch(
        "yoke_core.engines.main_checkout_sync.sync_main_checkout_at_session_start",
    ):
        yield


@pytest.mark.parametrize(
    "executor_family, registration_target",
    [
        ("claude", "yoke_core.hooks.session_dispatch._run_claude_session_start"),
        ("codex", "yoke_core.hooks.session_dispatch._run_codex_session_start"),
        (
            "cursor",
            "yoke_core.hooks.session_dispatch_cursor.run_session_start",
        ),
    ],
)
def test_session_start_reaps_after_registration_on_every_family(
    _quiet_start, executor_family: str, registration_target: str,
) -> None:
    order = mock.Mock()
    with mock.patch(
        registration_target, return_value="",
    ) as register, mock.patch(
        "yoke_core.hooks.session_start_stale_cleanup"
        ".run_session_start_stale_cleanup",
    ) as reap:
        order.attach_mock(register, "register")
        order.attach_mock(reap, "reap")
        session_dispatch.evaluate(_session_start(executor_family))

    register.assert_called_once()
    reap.assert_called_once_with(
        "/Users/x/yoke",
        session_id="sess-start",
        executor=executor_family,
        event_source="SessionStart",
    )
    assert [call[0] for call in order.mock_calls] == ["register", "reap"]


def test_session_start_preserves_family_stdout(_quiet_start) -> None:
    with mock.patch(
        "yoke_core.hooks.session_dispatch._run_codex_session_start",
        return_value="## Yoke Orientation\n",
    ), mock.patch(
        "yoke_core.hooks.session_start_stale_cleanup"
        ".run_session_start_stale_cleanup",
    ):
        decision = session_dispatch.evaluate(_session_start("codex"))

    assert decision.audit_fields["stdout"] == "## Yoke Orientation\n"


def test_reap_runs_the_shared_janitor_and_closes_its_connection() -> None:
    conn_obj = _FakeConn()
    swept: list = []

    ran = _reap.run_session_start_stale_cleanup(
        "/repo",
        executor="claude-code",
        _connect=lambda _timeout_ms: conn_obj,
        _cleanup=swept.append,
    )

    assert ran is True
    assert swept == [conn_obj]
    assert conn_obj.closed is True


def test_reap_skips_a_control_plane_with_no_local_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The relayed SessionStart already reaps server-side; this is not a failure."""
    sent: list = []
    monkeypatch.setattr(
        _reap, "emit_session_hook_failed", lambda **kw: sent.append(kw),
    )
    monkeypatch.setattr(_reap, "local_connection_or_none", lambda _open: None)

    def _unreachable(_conn):
        raise AssertionError("swept without a local connection")

    ran = _reap.run_session_start_stale_cleanup(
        "/repo", executor="claude-code", _cleanup=_unreachable,
    )

    assert ran is False
    assert sent == []


def test_reap_reports_a_failed_sweep_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list = []
    monkeypatch.setattr(
        _reap, "emit_session_hook_failed", lambda **kw: sent.append(kw),
    )
    conn_obj = _FakeConn()

    def _boom(_conn):
        raise RuntimeError("contention")

    ran = _reap.run_session_start_stale_cleanup(
        "/repo",
        session_id="sess-start",
        executor="codex",
        _connect=lambda _timeout_ms: conn_obj,
        _cleanup=_boom,
    )

    assert ran is False
    assert conn_obj.closed is True
    assert len(sent) == 1
    assert sent[0]["hook_event"] == "SessionStart"
    assert sent[0]["executor"] == "codex"
    assert sent[0]["reason"] == "RuntimeError"
    assert sent[0]["session_id"] == "sess-start"


def _age(conn_obj, session_id: str, minutes: int) -> None:
    old = _ago_minutes(minutes)
    conn_obj.execute(
        "UPDATE harness_sessions SET offered_at=%s, last_heartbeat=%s "
        "WHERE session_id=%s",
        (old, old, session_id),
    )
    conn_obj.execute(
        "UPDATE work_claims SET claimed_at=%s, last_heartbeat=%s "
        "WHERE session_id=%s AND released_at IS NULL",
        (old, old, session_id),
    )
    conn_obj.commit()


def _ended_at(conn_obj, session_id: str):
    return conn_obj.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone()["ended_at"]


def test_local_session_start_sweeps_only_the_stale_claimless_session(
    conn, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _insert_claimable_items(conn, 9301)
    _register(conn, session_id="stale-claimless")
    _age(conn, "stale-claimless", 30)

    _register(conn, session_id="fresh-session")
    _age(conn, "fresh-session", 1)

    _register(conn, session_id="holding-session")
    claim_work(conn, session_id="holding-session", item_id=9301)
    _age(conn, "holding-session", 30)

    _register(conn, session_id="in-flight-session")
    _age(conn, "in-flight-session", 30)
    # An unfinished tool call that is still the session's newest activity:
    # a long command is running, and the base threshold alone must not end it.
    open_call_at = _ago_minutes(25)
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s, tool_call_count=3 "
        "WHERE session_id='in-flight-session'",
        (open_call_at,),
    )
    conn.execute(
        "INSERT INTO session_tool_calls "
        "(session_id, tool_use_id, tool_name, started_at) "
        "VALUES ('in-flight-session', 'call-1', 'Bash', %s)",
        (open_call_at,),
    )
    conn.commit()

    monkeypatch.setattr(
        _reap, "local_connection_or_none", lambda _open: _KeepOpenConn(conn),
    )
    with mock.patch(
        "yoke_core.hooks.session_dispatch._root_and_db",
        return_value=(str(tmp_path), str(tmp_path / "yoke.db")),
    ), mock.patch(
        "yoke_core.hooks.session_dispatch._is_yoke_target", return_value=True,
    ), mock.patch(
        "yoke_core.engines.main_checkout_sync.sync_main_checkout_at_session_start",
    ), mock.patch(
        "yoke_core.hooks.session_dispatch._run_claude_session_start",
    ):
        session_dispatch.evaluate(_session_start("claude"))

    assert _ended_at(conn, "stale-claimless") is not None
    assert _ended_at(conn, "fresh-session") is None
    assert _ended_at(conn, "holding-session") is None
    assert _ended_at(conn, "in-flight-session") is None
