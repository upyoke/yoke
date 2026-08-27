# ruff: noqa: F811
"""Applying one machine's verified-dead session reports."""

from __future__ import annotations

import pytest

from runtime.api.sessions_api_stale_test_helpers import _ago_minutes
from runtime.api.test_sessions import (
    _insert_claimable_items,
    _register,
    conn,  # noqa: F401
)
from yoke_core.domain import session_process_liveness_end as liveness_end
from yoke_core.domain import sessions_analytics
from yoke_core.domain.sessions_analytics import EVENT_HARNESS_SESSION_ENDED
from yoke_core.domain.session_process_liveness_end import (
    PROCESS_VERIFIED_DEAD_REASON,
    end_process_verified_dead_sessions,
)
from yoke_core.domain.sessions import claim_work
from yoke_core.domain.sessions_analytics import SessionError


MACHINE = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
OTHER_MACHINE = "3f2504e0-4f89-41d3-9a0c-0305e82c3302"
EVIDENCE = {"records_considered": 1, "sources": ["launch_handle"], "pids": [4002]}


@pytest.fixture(autouse=True)
def _claimable_items(conn):
    _insert_claimable_items(conn, 9301)


def _ghost(conn, session_id: str = "sess-ghost", *, machine_id: str = MACHINE) -> str:
    _register(conn, session_id=session_id, machine_id=machine_id)
    old = _ago_minutes(120)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=%s, last_heartbeat=%s, "
        "last_tool_call_at=%s WHERE session_id=%s",
        (machine_id, old, old, session_id),
    )
    conn.commit()
    return session_id


def _apply(conn, session_id: str, *, projects=(1,), machine_id: str = MACHINE):
    return end_process_verified_dead_sessions(
        conn,
        machine_id=machine_id,
        authorized_projects=projects,
        reports=[{"session_id": session_id, "evidence": EVIDENCE}],
    )


def _ended_at(conn, session_id: str):
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    return row["ended_at"]


def test_a_stale_session_on_this_machine_is_ended(conn):
    session_id = _ghost(conn)
    result = _apply(conn, session_id)
    assert result == {"ended": [session_id], "skipped": []}
    assert _ended_at(conn, session_id)


def test_ending_releases_the_claims_the_dead_process_still_held(conn):
    session_id = _ghost(conn)
    claim_work(conn, session_id=session_id, item_id=9301)
    assert _apply(conn, session_id)["ended"] == [session_id]
    held = conn.execute(
        "SELECT COUNT(*) AS cnt FROM work_claims "
        "WHERE session_id=%s AND released_at IS NULL",
        (session_id,),
    ).fetchone()["cnt"]
    assert held == 0


def test_the_terminal_event_names_the_verified_dead_process(conn, monkeypatch):
    emitted: list[dict] = []

    def _capture(event_name, *, session_id, context, **kwargs):
        emitted.append(
            {"event_name": event_name, "session_id": session_id, "context": context}
        )

    monkeypatch.setattr(sessions_analytics, "_emit_session_event", _capture)
    session_id = _ghost(conn)
    _apply(conn, session_id)
    ends = [
        entry for entry in emitted if entry["event_name"] == EVENT_HARNESS_SESSION_ENDED
    ]
    assert ends, "session end must be on the ledger"
    context = ends[-1]["context"]
    assert context["reason"] == PROCESS_VERIFIED_DEAD_REASON
    evidence = context["agent_presence_evidence"]
    assert evidence["source"] == "relay_process_probe"
    assert evidence["verdict"] == PROCESS_VERIFIED_DEAD_REASON
    assert evidence["pids"] == EVIDENCE["pids"]


def test_a_session_whose_heartbeat_is_fresh_is_left_alone(conn):
    _register(conn, session_id="sess-live", machine_id=MACHINE)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=%s WHERE session_id=%s",
        (MACHINE, "sess-live"),
    )
    conn.commit()
    result = _apply(conn, "sess-live")
    assert result["ended"] == []
    assert result["skipped"] == [
        {"session_id": "sess-live", "status": "liveness_active"}
    ]
    assert _ended_at(conn, "sess-live") is None


def test_a_session_on_another_machine_is_refused(conn):
    session_id = _ghost(conn, "sess-elsewhere", machine_id=OTHER_MACHINE)
    result = _apply(conn, session_id)
    assert result["skipped"] == [
        {"session_id": session_id, "status": "machine_mismatch"}
    ]
    assert _ended_at(conn, session_id) is None


def test_a_project_the_relay_does_not_serve_is_refused(conn):
    session_id = _ghost(conn)
    result = _apply(conn, session_id, projects=(4242,))
    assert result["skipped"] == [
        {"session_id": session_id, "status": "project_unauthorized"}
    ]
    assert _ended_at(conn, session_id) is None


def test_an_unknown_session_is_named_rather_than_dropped(conn):
    result = _apply(conn, "sess-never-registered")
    assert result["skipped"] == [
        {"session_id": "sess-never-registered", "status": "session_not_found"}
    ]


def test_a_refused_end_is_named_rather_than_raised(conn, monkeypatch):
    session_id = _ghost(conn)

    def _refuse(*args, **kwargs):
        raise SessionError("CHAIN_PENDING", "checkpoint still has budget")

    monkeypatch.setattr(liveness_end, "end_session", _refuse)
    result = _apply(conn, session_id)
    assert result["ended"] == []
    assert result["skipped"] == [
        {"session_id": session_id, "status": "refused_chain_pending"}
    ]


def test_a_second_report_of_an_already_ended_session_is_a_no_op(conn):
    session_id = _ghost(conn)
    assert _apply(conn, session_id)["ended"] == [session_id]
    repeat = _apply(conn, session_id)
    assert repeat["ended"] == []
    assert repeat["skipped"] == [
        {"session_id": session_id, "status": "liveness_ended"}
    ]
