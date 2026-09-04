# ruff: noqa: F811
"""Applying one machine's verified-dead native-process reports."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.sessions_api_stale_test_helpers import _ago_minutes
from runtime.api.test_sessions import (
    _insert_claimable_items,
    _register,
)
from yoke_core.domain import session_process_liveness_report as liveness_report
from yoke_core.domain import sessions_analytics
from yoke_core.domain.session_native_process_observation import (
    CLAIMS_HELD_STATUS,
    current_native_process_observation,
)
from yoke_core.domain.session_process_liveness_report import (
    PROCESS_VERIFIED_DEAD_REASON,
    apply_verified_process_death_reports,
)
from yoke_core.domain.sessions import claim_work
from yoke_core.domain.sessions_analytics import (
    EVENT_HARNESS_SESSION_ENDED,
    SessionError,
)


MACHINE = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
OTHER_MACHINE = "3f2504e0-4f89-41d3-9a0c-0305e82c3302"
LAUNCH_ID = "9f1f2d4e-0f7a-4a71-9a1a-6a0c0b6f2d10"
EVIDENCE = {
    "records_considered": 1,
    "sources": ["launch_handle"],
    "pids": [4002],
    "process_start_times": {"4002": "1699999999"},
    "launch_id": LAUNCH_ID,
}
#: What an anchor a hook wrote reports: a pid, and no launch behind it.
ANCHOR_EVIDENCE = {
    "records_considered": 1,
    "sources": ["process_anchor"],
    "pids": [4003],
    "process_start_times": {"4003": "1699999998"},
}


@pytest.fixture(autouse=True)
def _claimable_items(conn):
    _insert_claimable_items(conn, 9301)


@pytest.fixture
def conn(test_db):
    return test_db


def _ghost(
    conn,
    session_id: str = "sess-ghost",
    *,
    machine_id: str = MACHINE,
    executor_surface: str | None = None,
) -> str:
    kwargs = {"machine_id": machine_id}
    if executor_surface:
        kwargs["executor"] = executor_surface
    _register(conn, session_id=session_id, **kwargs)
    old = _ago_minutes(120)
    conn.execute(
        "UPDATE harness_sessions SET machine_id=%s, last_heartbeat=%s, "
        "last_tool_call_at=%s WHERE session_id=%s",
        (machine_id, old, old, session_id),
    )
    conn.commit()
    return session_id


def _apply(
    conn,
    session_id: str,
    *,
    projects=(1,),
    machine_id: str = MACHINE,
    evidence=None,
):
    return apply_verified_process_death_reports(
        conn,
        machine_id=machine_id,
        authorized_projects=projects,
        reports=[
            {
                "session_id": session_id,
                "evidence": EVIDENCE if evidence is None else evidence,
            }
        ],
    )


def _session_row(conn, session_id: str):
    return dict(
        conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (session_id,)
        ).fetchone()
    )


def test_a_stale_claimless_session_on_this_machine_is_ended(conn):
    session_id = _ghost(conn)
    assert _apply(conn, session_id) == {
        "ended": [session_id],
        "launches_corrected": [],
        "skipped": [],
    }
    assert _session_row(conn, session_id)["ended_at"]


@pytest.mark.parametrize("executor_surface", ["claude-desktop", "claude-cli"])
def test_desktop_and_headless_claim_holders_are_spared(conn, executor_surface):
    session_id = _ghost(conn, executor_surface=executor_surface)
    claim_work(conn, session_id=session_id, item_id=9301)

    assert _apply(conn, session_id) == {
        "ended": [],
        "launches_corrected": [],
        "skipped": [{"session_id": session_id, "status": CLAIMS_HELD_STATUS}],
    }
    row = _session_row(conn, session_id)
    assert row["ended_at"] is None
    assert current_native_process_observation(row) == {
        "state": "gone",
        "observed_at": row["native_process_gone_at"],
        "evidence": EVIDENCE,
    }
    assert (
        conn.execute(
            "SELECT COUNT(*) AS cnt FROM work_claims "
            "WHERE session_id=%s AND released_at IS NULL",
            (session_id,),
        ).fetchone()["cnt"]
        == 1
    )


@pytest.mark.parametrize(
    "holding_kind",
    ["work_claim", "path_claim", "strategy_document", "coordination"],
)
def test_every_shared_projection_holding_blocks_process_death_end(
    conn, monkeypatch, holding_kind
):
    session_id = _ghost(conn)
    monkeypatch.setattr(
        liveness_report,
        "session_holdings_by_session",
        lambda _conn, previous_limit=0: {
            session_id: {"current": [{"holding_kind": holding_kind}]}
        },
    )

    assert _apply(conn, session_id)["skipped"] == [
        {"session_id": session_id, "status": CLAIMS_HELD_STATUS}
    ]
    assert _session_row(conn, session_id)["ended_at"] is None


def test_new_activity_supersedes_the_process_gone_observation(conn):
    session_id = _ghost(conn)
    claim_work(conn, session_id=session_id, item_id=9301)
    _apply(conn, session_id)
    later = datetime.now(timezone.utc) + timedelta(seconds=2)
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s, episode_started_at=%s "
        "WHERE session_id=%s",
        (later.isoformat(), later.isoformat(), session_id),
    )
    row = _session_row(conn, session_id)
    assert current_native_process_observation(row) is None


def test_the_claimless_terminal_event_names_the_verified_dead_process(
    conn, monkeypatch
):
    emitted: list[dict] = []

    def _capture(event_name, *, session_id, context, **kwargs):
        emitted.append({"event_name": event_name, "context": context})

    monkeypatch.setattr(sessions_analytics, "_emit_session_event", _capture)
    session_id = _ghost(conn)
    _apply(conn, session_id)
    context = next(
        entry["context"]
        for entry in reversed(emitted)
        if entry["event_name"] == EVENT_HARNESS_SESSION_ENDED
    )
    assert context["reason"] == PROCESS_VERIFIED_DEAD_REASON
    assert context["agent_presence_evidence"]["pids"] == EVIDENCE["pids"]


def test_fresh_wrong_machine_and_unauthorized_reports_are_refused(conn):
    _register(conn, session_id="sess-live", machine_id=MACHINE)
    assert _apply(conn, "sess-live", evidence=ANCHOR_EVIDENCE)["skipped"] == [
        {"session_id": "sess-live", "status": "liveness_active"}
    ]
    elsewhere = _ghost(conn, "sess-elsewhere", machine_id=OTHER_MACHINE)
    assert _apply(conn, elsewhere)["skipped"] == [
        {"session_id": elsewhere, "status": "machine_mismatch"}
    ]
    unauthorized = _ghost(conn, "sess-unauthorized")
    assert _apply(conn, unauthorized, projects=(4242,))["skipped"] == [
        {"session_id": unauthorized, "status": "project_unauthorized"}
    ]


def test_unknown_and_refused_claimless_ends_are_named(conn, monkeypatch):
    assert _apply(conn, "sess-never-registered")["skipped"] == [
        {"session_id": "sess-never-registered", "status": "session_not_found"}
    ]
    session_id = _ghost(conn)

    def _refuse(*args, **kwargs):
        raise SessionError("CHAIN_PENDING", "checkpoint still has budget")

    monkeypatch.setattr(liveness_report, "end_session", _refuse)
    assert _apply(conn, session_id)["skipped"] == [
        {"session_id": session_id, "status": "refused_chain_pending"}
    ]


def test_a_second_report_of_an_already_ended_session_is_a_no_op(conn):
    session_id = _ghost(conn)
    assert _apply(conn, session_id)["ended"] == [session_id]
    assert _apply(conn, session_id)["skipped"] == [
        {"session_id": session_id, "status": "liveness_ended"}
    ]
