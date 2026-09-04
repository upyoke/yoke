# ruff: noqa: F811
"""Answering a machine's idle-host question and recording what it reclaimed."""

from __future__ import annotations

import json

import pytest

from runtime.api.test_sessions import _register
from yoke_core.domain.session_idle_host_report import (
    EVENT_NATIVE_HOST_RECLAIMED,
    SESSION_LIVE_STATUS,
    apply_idle_host_report,
)
from yoke_core.domain.sessions_render_end import end_session


MACHINE = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
OTHER_MACHINE = "3f2504e0-4f89-41d3-9a0c-0305e82c3302"
RECLAIMED = {
    "pid": 4002,
    "action": "stopped_job",
    "result": "terminated",
    "job_state": "done",
    "age_seconds": 86400,
    "idle_seconds": 7200,
    "rss_kb": 512000,
}


@pytest.fixture
def conn(test_db):
    return test_db


def _session(conn, session_id: str, *, machine_id: str = MACHINE, ended=False) -> str:
    _register(conn, session_id=session_id, machine_id=machine_id)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=%s WHERE session_id=%s",
        (machine_id, session_id),
    )
    if ended:
        end_session(conn, session_id, release_claims=False)
    conn.commit()
    return session_id


def _apply(conn, *, hosts=(), reclaimed=(), machine_id: str = MACHINE):
    return apply_idle_host_report(
        conn,
        machine_id=machine_id,
        authorized_projects=(1,),
        hosts=[{"session_id": session_id, "pid": 4001} for session_id in hosts],
        reclaimed=[{"session_id": session_id, **RECLAIMED} for session_id in reclaimed],
    )


def test_only_ended_sessions_on_this_machine_are_answered_ended(conn):
    ended = _session(conn, "sess-ended", ended=True)
    live = _session(conn, "sess-live")
    elsewhere = _session(conn, "sess-elsewhere", machine_id=OTHER_MACHINE, ended=True)

    outcome = _apply(conn, hosts=[ended, live, elsewhere, "sess-unknown"])

    assert outcome == {
        "ended": [ended],
        "skipped": [
            {"session_id": live, "status": SESSION_LIVE_STATUS},
            {"session_id": elsewhere, "status": "machine_mismatch"},
            {"session_id": "sess-unknown", "status": "session_not_found"},
        ],
        "recorded": [],
    }


def test_a_reclaimed_host_lands_as_an_event_on_its_session(conn):
    ended = _session(conn, "sess-reclaimed", ended=True)

    outcome = _apply(conn, reclaimed=[ended])
    conn.commit()

    assert outcome == {"ended": [], "skipped": [], "recorded": [ended]}
    rows = conn.execute(
        "SELECT envelope FROM events WHERE event_name=%s",
        (EVENT_NATIVE_HOST_RECLAIMED,),
    ).fetchall()
    assert len(rows) == 1
    envelope = rows[0][0]
    if isinstance(envelope, str):
        envelope = json.loads(envelope)
    context = envelope["context"]
    assert context["session_id"] == ended
    assert context["machine_id"] == MACHINE
    assert context["source"] == "relay_idle_host_reclaim"
    for key, value in RECLAIMED.items():
        assert context[key] == value


def test_a_reclaimed_host_from_another_machine_is_refused_by_name(conn):
    elsewhere = _session(conn, "sess-foreign", machine_id=OTHER_MACHINE, ended=True)

    outcome = _apply(conn, reclaimed=[elsewhere])

    assert outcome == {
        "ended": [],
        "skipped": [{"session_id": elsewhere, "status": "machine_mismatch"}],
        "recorded": [],
    }
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_name=%s",
            (EVENT_NATIVE_HOST_RECLAIMED,),
        ).fetchone()[0]
        == 0
    )
