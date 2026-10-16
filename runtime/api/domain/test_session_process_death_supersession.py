"""A resumed session survives repeated reports about its previous native."""

from datetime import datetime, timedelta, timezone

import pytest
from psycopg.errors import LockNotAvailable

from runtime.api.domain.test_session_process_liveness_report import (
    EVIDENCE,
    _apply,
    _ghost,
    _session_row,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.test_sessions import _insert_claimable_items
from yoke_core.domain import session_process_liveness_report as reporter
from yoke_core.domain.session_native_process_observation import (
    record_native_process_gone,
)
from yoke_core.domain.sessions import claim_work
from yoke_core.domain.sessions_lifecycle_release_bulk import release_all_claims


@pytest.fixture
def conn(test_db):
    _insert_claimable_items(test_db, 9301)
    return test_db


def _death(conn, session_id):
    death = datetime.now(timezone.utc) - timedelta(minutes=2)
    conn.execute(
        "UPDATE harness_sessions SET episode_started_at=%s WHERE session_id=%s",
        (death, session_id),
    )
    record_native_process_gone(conn, session_id, EVIDENCE, observed_at=death)
    conn.commit()
    return death


@pytest.mark.parametrize(
    "activity", ["last_heartbeat", "last_tool_call_at", "episode_started_at"]
)
def test_repeat_launch_report_cannot_end_resumed_claimless_handoff(conn, activity):
    session_id = _ghost(conn)
    claim_work(conn, session_id=session_id, item_id=9301)
    assert _apply(conn, session_id)["skipped"][0]["status"] == "claims_held"
    death = _session_row(conn, session_id)["native_process_gone_at"]
    resumed = death + timedelta(microseconds=1)
    conn.execute(
        f"UPDATE harness_sessions SET {activity}=%s WHERE session_id=%s",
        (resumed, session_id),
    )
    conn.commit()
    release_all_claims(conn, session_id=session_id, reason="released")

    for _ in range(2):
        assert _apply(conn, session_id)["skipped"] == [
            {"session_id": session_id, "status": "process_death_superseded"}
        ]
        row = _session_row(conn, session_id)
        assert row["ended_at"] is None
        assert row["native_process_gone_at"] == death
    assert claim_work(conn, session_id=session_id, item_id=9301)["id"]


def test_late_first_report_uses_native_exit_time_instead_of_arrival(conn):
    session_id = _ghost(conn)
    death = datetime.now(timezone.utc) - timedelta(minutes=2)
    resumed = death + timedelta(seconds=1)
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s WHERE session_id=%s",
        (resumed, session_id),
    )
    conn.commit()

    assert _apply(conn, session_id, evidence={**EVIDENCE, "native_exit_at": death})[
        "skipped"
    ] == [{"session_id": session_id, "status": "process_death_superseded"}]
    assert _session_row(conn, session_id)["native_process_gone_at"] == death


def test_activity_winning_lifecycle_lock_is_reread_before_ending(conn, monkeypatch):
    session_id = _ghost(conn)
    death = _death(conn, session_id)
    lock = reporter.lock_session_rows_for_claim_lifecycle

    def activity_then_lock(connection, session_ids):
        with connect_test_database(str(conn.info.dbname)) as activity_conn:
            activity_conn.execute(
                "UPDATE harness_sessions SET last_tool_call_at=%s WHERE session_id=%s",
                (death + timedelta(seconds=1), session_id),
            )
            activity_conn.commit()
        return lock(connection, session_ids)

    monkeypatch.setattr(
        reporter, "lock_session_rows_for_claim_lifecycle", activity_then_lock
    )
    assert _apply(conn, session_id)["skipped"] == [
        {"session_id": session_id, "status": "process_death_superseded"}
    ]
    assert _session_row(conn, session_id)["ended_at"] is None


def test_lifecycle_lock_is_held_through_destructive_end(conn, monkeypatch):
    session_id = _ghost(conn)
    end = reporter.end_session

    def assert_locked_then_end(connection, target, **kwargs):
        with connect_test_database(str(conn.info.dbname)) as contender:
            with pytest.raises(LockNotAvailable):
                contender.execute(
                    "SELECT session_id FROM harness_sessions WHERE session_id=%s "
                    "FOR UPDATE NOWAIT",
                    (session_id,),
                )
            contender.rollback()
        return end(connection, target, **kwargs)

    monkeypatch.setattr(reporter, "end_session", assert_locked_then_end)
    assert _apply(conn, session_id)["ended"] == [session_id]


def test_activity_equal_to_death_still_allows_immediate_settlement(conn):
    session_id = _ghost(conn)
    death = _death(conn, session_id)
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s WHERE session_id=%s",
        (death, session_id),
    )
    conn.commit()
    assert _apply(conn, session_id)["ended"] == [session_id]
