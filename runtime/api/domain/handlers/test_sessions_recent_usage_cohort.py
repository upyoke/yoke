"""The 24-hour usage cohort's two halves: `sessions.list` with `usage_last_24h`.

A machine's 24-hour figures answer for the union of sessions that ENDED
inside the trailing 24 hours and sessions that STARTED inside it and have not
ended, each counted exactly once. The ended half's own dating, project
scoping, and payload validation live beside it in
``test_sessions_recent_usage_by_machine``; this module owns the union — that
a running machine reads as busy, that a long-running session's cumulative
usage is not a reading of this window, that neither half double-counts, and
where each half's boundary falls.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_contracts.session_usage_facts import (
    USAGE_COMPLETE,
    ModelUsage,
    SessionUsage,
    usage_document,
)
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.session_control_schema import create_session_control_tables


def _iso(hours_ago: float = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _usage(tokens: int) -> str:
    return usage_document(SessionUsage(
        status=USAGE_COMPLETE,
        models=(ModelUsage(model="test-model", input=tokens),),
    ))


def _insert_session(
    conn,
    session_id: str,
    *,
    ended_at: str | None = None,
    offered_at: str | None = None,
    usage_tokens: int = 1_000,
) -> None:
    # A nonzero tool-call count keeps these fixtures out of the startup-probe
    # exclusion, which reads `offered_at` equal to the end stamp with no tool
    # calls as a probe rather than a real session.
    activity = offered_at or ended_at or _iso()
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, tool_call_count, "
        "ended_at, machine_id, usage_totals"
        ") VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s, %s, 1, %s, %s, %s)",
        (
            session_id, "claude-code", "anthropic", "test-model", "primary",
            "/tmp/workspace", "wait", activity, activity, ended_at,
            "machine-one", _usage(usage_tokens),
        ),
    )
    conn.commit()


def _request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"usage_last_24h": True},
    )


def test_open_session_started_in_the_window_is_included(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    # A machine running work right now reads as busy: the still-open half of
    # the cohort is what the ended-only window could never show.
    _insert_session(test_db, "open-recent", offered_at=_iso(2), usage_tokens=2_000)
    _insert_session(test_db, "ended", ended_at=_iso(1), usage_tokens=500)

    rows = handle_sessions_list(_request()).result_payload["rows"]
    assert sorted(row["session_id"] for row in rows) == ["ended", "open-recent"]
    assert sum(row["usage_tokens"] for row in rows) == 2_500


def test_open_session_started_before_the_window_is_excluded(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    # A long-running session's cumulative usage is not a reading of the last
    # 24 hours, so it stays out however much it has spent.
    _insert_session(test_db, "open-old", offered_at=_iso(30), usage_tokens=9_000)
    _insert_session(test_db, "open-recent", offered_at=_iso(3), usage_tokens=40)

    rows = handle_sessions_list(_request()).result_payload["rows"]
    assert [row["session_id"] for row in rows] == ["open-recent"]


def test_each_session_is_counted_once_across_both_halves(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    # Started inside the window AND ended inside it: the halves are exact
    # complements on whether a session has ended, so the union cannot
    # double-count this row and its tokens land once.
    _insert_session(
        test_db, "started-and-ended", offered_at=_iso(4), ended_at=_iso(1),
        usage_tokens=1_200,
    )
    _insert_session(test_db, "open-recent", offered_at=_iso(2), usage_tokens=300)

    rows = handle_sessions_list(_request()).result_payload["rows"]
    assert [row["session_id"] for row in rows].count("started-and-ended") == 1
    assert len(rows) == 2
    assert sum(row["usage_tokens"] for row in rows) == 1_500


def test_window_boundary_includes_both_halves_at_the_cutoff(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    # The cutoff is inclusive on both halves, and one second past it is out.
    inside = 24 - 1 / 3600
    outside = 24 + 1 / 3600
    _insert_session(test_db, "ended-at-cutoff", ended_at=_iso(inside), usage_tokens=1)
    _insert_session(
        test_db, "ended-past-cutoff", ended_at=_iso(outside), usage_tokens=2,
    )
    _insert_session(
        test_db, "open-at-cutoff", offered_at=_iso(inside), usage_tokens=4,
    )
    _insert_session(
        test_db, "open-past-cutoff", offered_at=_iso(outside), usage_tokens=8,
    )

    rows = handle_sessions_list(_request()).result_payload["rows"]
    assert sorted(row["session_id"] for row in rows) == [
        "ended-at-cutoff", "open-at-cutoff",
    ]
