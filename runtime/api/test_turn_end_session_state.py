"""The session reads behind a Stop decision: declared park, CI wait, waiter."""

from __future__ import annotations

import sqlite3

from yoke_core.domain import turn_end_session_state as state
from yoke_core.domain.session_ci_wait_schema import (
    SESSION_CI_RUN_WAITS_CREATE_SQL,
)
from yoke_core.domain.session_tool_call_projections import (
    LAST_COMPLETED_TOOL_COLUMN,
)


class _Rows:
    def __init__(self, row: dict | None) -> None:
        self._row = row

    def fetchone(self) -> dict | None:
        return self._row


class _SessionConn:
    """Answers the session reads the gate makes, and records them."""

    def __init__(self, row: dict | None) -> None:
        self._row = row
        self.queries: list[str] = []

    def execute(self, query: str, params: tuple[object, ...]) -> _Rows:
        self.queries.append(query)
        return _Rows(self._row)


def _no_events(monkeypatch) -> None:
    """The waiter fact comes from the call rows, so events are never read."""
    monkeypatch.setattr(
        "yoke_core.domain.session_tool_call_projections.has_session_tool_calls_table",
        lambda conn: True,
    )


def test_a_parked_session_reads_as_parked() -> None:
    conn = _SessionConn({"mode": "parked"})

    assert state.session_parked(conn, "sess-1") is True


def test_any_other_mode_is_not_parked() -> None:
    conn = _SessionConn({"mode": "dash"})

    assert state.session_parked(conn, "sess-1") is False


def test_an_unknown_session_is_not_parked() -> None:
    conn = _SessionConn(None)

    assert state.session_parked(conn, "sess-1") is False


def test_waiter_armed_for_a_last_monitor_call(monkeypatch) -> None:
    _no_events(monkeypatch)
    conn = _SessionConn({LAST_COMPLETED_TOOL_COLUMN: "Monitor"})

    assert state.monitor_waiter_armed(conn, "sess-1") is True
    assert not any("events" in query for query in conn.queries)


def test_waiter_not_armed_when_the_last_call_was_something_else(
    monkeypatch,
) -> None:
    _no_events(monkeypatch)
    conn = _SessionConn({LAST_COMPLETED_TOOL_COLUMN: "Bash"})

    assert state.monitor_waiter_armed(conn, "sess-1") is False


def _ci_wait_conn(notified_at: str | None) -> sqlite3.Connection:
    """A real table holding one recorded wait for ``sess-1``."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SESSION_CI_RUN_WAITS_CREATE_SQL)
    conn.execute(
        "INSERT INTO session_ci_run_waits "
        "(session_id, project_id, repo, run_id, kind, created_at, notified_at) "
        "VALUES ('sess-1', 1, 'upyoke/yoke', '77', 'merge_verification', "
        "'2026-10-26T13:00:00Z', ?)",
        (notified_at,),
    )
    return conn


def test_an_open_ci_wait_is_pending() -> None:
    assert state.ci_wait_pending(_ci_wait_conn(None), "sess-1") is True


def test_a_notified_ci_wait_is_not_pending() -> None:
    conn = _ci_wait_conn("2026-10-26T13:20:00Z")

    assert state.ci_wait_pending(conn, "sess-1") is False


def test_another_sessions_ci_wait_is_not_pending() -> None:
    assert state.ci_wait_pending(_ci_wait_conn(None), "sess-2") is False
