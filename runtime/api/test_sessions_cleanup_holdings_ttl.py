# ruff: noqa: F811
"""Holdings-aware TTL coverage for the stale-session sweep."""

from __future__ import annotations

import pytest

from runtime.api.sessions_api_stale_test_helpers import (
    _ago_minutes,
    apply_ddl_statements,
)
from runtime.api.test_sessions import (
    _insert_claimable_items,
    _register,
    conn,  # noqa: F401
)
from yoke_core.domain.session_cleanup_holdings import active_holding_sessions
from yoke_core.domain.sessions import claim_work, clean_stale_harness_sessions


_STRATEGY_LOCK_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy_doc_claims (
    id INTEGER PRIMARY KEY,
    owner_kind TEXT NOT NULL,
    owner_session_id TEXT,
    released_at TEXT
);
"""


@pytest.fixture(autouse=True)
def _holding_schema(conn):
    _insert_claimable_items(conn, 9201, 9202)
    apply_ddl_statements(conn, _STRATEGY_LOCK_SCHEMA)
    conn.commit()


def _age_session(conn, session_id: str, minutes: int) -> str:
    old = _ago_minutes(minutes)
    conn.execute(
        "UPDATE harness_sessions SET offered_at=%s, last_heartbeat=%s "
        "WHERE session_id=%s",
        (old, old, session_id),
    )
    conn.execute(
        "UPDATE work_claims SET claimed_at=%s, last_heartbeat=%s "
        "WHERE session_id=%s AND released_at IS NULL",
        (old, old, session_id),
    )
    conn.commit()
    return old


def _add_holding(conn, session_id: str, kind: str) -> None:
    if kind == "work_claim":
        claim_work(conn, session_id=session_id, item_id=9201)
        return
    if kind == "strategy_lock":
        conn.execute(
            "INSERT INTO strategy_doc_claims "
            "(owner_kind, owner_session_id) VALUES ('session', %s)",
            (session_id,),
        )
    elif kind == "coordination_lease":
        now = _ago_minutes(1)
        conn.execute(
            "INSERT INTO coordination_leases "
            "(project_id, lease_key, session_id, acquired_at, heartbeat_at, "
            "owner_kind, owner_session_id) "
            "VALUES (1, %s, %s, %s, %s, 'session', %s)",
            (f"TEST:{session_id}", session_id, now, now, session_id),
        )
    else:
        raise AssertionError(f"unsupported holding kind: {kind}")
    conn.commit()


def test_empty_session_keeps_the_short_ttl(conn):
    _register(conn, session_id="empty-session")
    _age_session(conn, "empty-session", 30)

    result = clean_stale_harness_sessions(conn, stale_threshold_minutes=20)

    assert result["total_reclaimed"] == 1
    entry = result["never_engaged"][0]
    assert entry["session_id"] == "empty-session"
    assert entry["effective_ttl_minutes"] == 20
    assert entry["has_active_holdings"] is False


@pytest.mark.parametrize(
    "holding_kind",
    ["work_claim", "strategy_lock", "coordination_lease"],
)
def test_active_holding_selects_the_long_ttl(conn, holding_kind):
    session_id = f"held-{holding_kind}"
    _register(conn, session_id=session_id)
    _add_holding(conn, session_id, holding_kind)
    _age_session(conn, session_id, 30)

    assert session_id in active_holding_sessions(conn)
    result = clean_stale_harness_sessions(conn, stale_threshold_minutes=20)

    assert result["total_reclaimed"] == 0
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    assert row["ended_at"] is None


def test_held_session_is_reclaimed_after_the_long_ttl(conn):
    _register(conn, session_id="expired-holder")
    _add_holding(conn, "expired-holder", "work_claim")
    _age_session(conn, "expired-holder", 300)

    result = clean_stale_harness_sessions(conn, stale_threshold_minutes=20)

    assert result["total_reclaimed"] == 1
    entry = result["never_engaged"][0]
    assert entry["effective_ttl_minutes"] == 240
    assert entry["has_active_holdings"] is True
    claim = conn.execute(
        "SELECT released_at FROM work_claims "
        "WHERE session_id='expired-holder' AND item_id=9201",
    ).fetchone()
    assert claim["released_at"] is not None


def test_holding_acquired_before_final_recheck_aborts_reclaim(conn, monkeypatch):
    _register(conn, session_id="late-holder")
    _age_session(conn, "late-holder", 30)
    snapshots = iter([set(), {"late-holder"}])

    from yoke_core.domain import sessions_cleanup

    monkeypatch.setattr(
        sessions_cleanup,
        "active_holding_sessions",
        lambda _conn: next(snapshots),
    )

    result = clean_stale_harness_sessions(conn, stale_threshold_minutes=20)

    assert result["total_reclaimed"] == 0
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id='late-holder'",
    ).fetchone()
    assert row["ended_at"] is None
