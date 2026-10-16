"""Automatic eligibility agrees across display, preview, and mutation."""

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.domain.handlers.test_sessions_list_handler import _insert_session
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.session_holdings import insert_item_claim, instant_ago
from yoke_core.domain.session_automatic_reclaim import automatic_reclaim
from yoke_core.domain.session_staleness import session_liveness
from yoke_core.domain.sessions_cleanup import clean_stale_harness_sessions
from yoke_core.domain.sessions_list_read import list_sessions
from yoke_core.domain.sessions_render_reclaim import find_stale_sessions

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
QUIET = NOW - timedelta(minutes=30)
OLD = NOW - timedelta(days=7)


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize(
    "fields,state",
    [
        ({}, "stale"),
        ({"last_heartbeat": NOW}, "active"),
        ({"holds_work_claim": True}, "active"),
        ({"holds_work_claim": True, "mode": "parked"}, "waiting"),
        ({"holds_work_claim": True, "turn_posture": "waiting"}, "waiting"),
        ({"mode": "parked"}, "stale"),
        ({"has_active_holdings": True}, "active"),
        ({"has_active_holdings": True, "last_heartbeat": OLD}, "stale"),
        ({"turn_posture": "running"}, "active"),
        ({"turn_posture": "running", "last_heartbeat": OLD}, "stale"),
        ({"open_tool_call_at": QUIET}, "active"),
        ({"open_tool_call_at": OLD}, "stale"),
        ({"ended_at": QUIET}, "ended"),
        ({"terminated_at": QUIET}, "ended"),
        ({"ended_at": QUIET, "holds_work_claim": True, "mode": "parked"}, "ended"),
        (
            {"last_heartbeat": NOW, "last_tool_call_at": OLD, "tool_call_count": 1},
            "stale",
        ),
        (
            {
                "last_heartbeat": NOW,
                "last_tool_call_at": OLD,
                "tool_call_count": 1,
                "episode_started_at": NOW,
            },
            "active",
        ),
    ],
)
def test_shared_snapshot_decision(executor, fields, state):
    row = {
        "session_id": "session",
        "executor": executor,
        "last_heartbeat": QUIET,
        "holds_work_claim": False,
        **fields,
    }
    decision = automatic_reclaim(row, now=NOW)
    assert session_liveness(row, now=NOW) == state
    assert decision.is_reclaimable == (state == "stale")


def test_roster_filters_preview_and_execution_agree(test_db):
    quiet = instant_ago(10_000)
    for executor in ("claude-code", "codex", "cursor"):
        for kind in ("quiet", "protected", "paused", "fresh", "ended", "killed"):
            sid = f"{executor}-{kind}"
            _insert_session(
                test_db,
                sid,
                executor=executor,
                last_heartbeat=instant_ago() if kind == "fresh" else quiet,
                ended_at=quiet if kind == "ended" else None,
                terminated_at=quiet if kind == "killed" else None,
            )
        for offset, kind in enumerate(("protected", "paused")):
            item_id = (
                100 + ("claude-code", "codex", "cursor").index(executor) * 2 + offset
            )
            insert_item(test_db, id=item_id, title="held work")
            test_db.commit()
            insert_item_claim(test_db, f"{executor}-{kind}", item_id)
        test_db.execute(
            "UPDATE harness_sessions SET turn_posture='waiting' WHERE session_id=%s",
            (f"{executor}-paused",),
        )
    test_db.commit()
    rows = list_sessions(limit=None)
    stale = {row["session_id"] for row in rows if row["liveness"] == "stale"}
    assert stale == {
        f"{executor}-quiet" for executor in ("claude-code", "codex", "cursor")
    }
    assert stale == {row["session_id"] for row in rows if row["reclaimable"]}
    assert stale == {
        row["session_id"] for row in list_sessions(liveness="stale", limit=None)
    }
    assert stale == {row["session_id"] for row in find_stale_sessions(test_db)}
    for row in rows:
        if row["session_id"].endswith("paused"):
            assert row["liveness"] == "waiting"
    result = clean_stale_harness_sessions(test_db, project_ids=[1])
    assert result["total_reclaimed"] == len(stale)
    assert {
        row["session_id"] for row in list_sessions(liveness="ended", limit=None)
    } >= stale


def test_execution_explains_a_new_work_claim(test_db, monkeypatch):
    from yoke_core.domain import sessions_cleanup

    _insert_session(test_db, "candidate", last_heartbeat=instant_ago(10_000))
    insert_item(test_db, id=101, title="newly held work")
    test_db.commit()
    classify = sessions_cleanup.classify_reclaimable

    def acquire_before_recheck(conn, sid, **kwargs):
        insert_item_claim(conn, sid, 101)
        return classify(conn, sid, **kwargs)

    monkeypatch.setattr(
        sessions_cleanup, "classify_reclaimable", acquire_before_recheck
    )
    result = clean_stale_harness_sessions(test_db, project_ids=[1])
    assert result["total_reclaimed"] == 0
    assert any(
        entry["session_id"] == "candidate"
        and entry["reason"] == "active_work_claim"
        and entry["recheck"]
        for entry in result["skipped_between_turns"]
    )
    assert list_sessions(session_id="candidate")[0]["liveness"] == "active"
