"""Claim-aware session auto-end behavior."""

from runtime.api.test_sessions import _insert_claimable_item, _register
from yoke_core.domain.sessions import claim_work, end_session_if_empty

pytest_plugins = ("runtime.api.test_sessions",)


def test_ends_claimless_active_session(conn):
    _register(conn, session_id="empty-end")

    result = end_session_if_empty(conn, "empty-end")

    assert result["status"] == "ended"
    assert result["ended"] is True
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id='empty-end'"
    ).fetchone()
    assert row["ended_at"] is not None


def test_skips_session_with_active_claims(conn):
    _register(conn, session_id="claimed-end")
    _insert_claimable_item(conn, 9999)
    claim_work(conn, session_id="claimed-end", item_id=9999)

    result = end_session_if_empty(conn, "claimed-end")

    assert result["status"] == "has_claims"
    assert result["ended"] is False
    assert result["active_claim_count"] == 1
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id='claimed-end'"
    ).fetchone()
    assert row["ended_at"] is None


def test_idempotent_when_already_ended(conn):
    _register(conn, session_id="already-ended")
    end_session_if_empty(conn, "already-ended")

    result = end_session_if_empty(conn, "already-ended")

    assert result["status"] == "already_ended"
    assert result["ended"] is False
