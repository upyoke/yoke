"""A silent active walk mails its owner once before the stale sweep aborts it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_plan_execution_authority_test_support import (
    _materialize_two_cases,
)
from yoke_contracts.timestamps import format_instant
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.fleet_delta_snapshot import session_rows
from yoke_core.domain.fleet_delta_stale_walks import stale_walks
from yoke_core.domain.qa_plan_execution_lifecycle import reap_stale_plan_executions
from yoke_core.domain.qa_plan_execution_silence_notice import silent_walks
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    select_plan_execution,
)
from yoke_core.domain.session_activity_state import apply_envelope_state

NOW = datetime(2026, 11, 19, 16, 30, tzinfo=timezone.utc)
SESSION = "session-silent-walker"


@pytest.fixture
def walk(test_db: Any) -> str:
    seed_qa_session(test_db, SESSION, messageable=True)
    test_db.execute(
        "UPDATE harness_sessions SET mode='dash' WHERE session_id=%s", (SESSION,)
    )
    _materialize_two_cases(test_db, item_id=5531)
    execution = begin_plan_execution(
        test_db,
        item_id=5531,
        transition_id="implemented",
        actor_id="1",
        session_id=SESSION,
    )
    test_db.commit()
    return str(execution["id"])


def _silence(conn: Any, execution_id: str, minutes: int, *, state: str = "") -> None:
    conn.execute(
        "UPDATE qa_plan_executions SET heartbeat_at=%s"
        + (", state=%s" if state else "")
        + " WHERE id=%s",
        (
            instant_parameter(conn, NOW - timedelta(minutes=minutes)),
            *((state,) if state else ()),
            execution_id,
        ),
    )
    conn.commit()


def _notices(conn: Any, execution_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT body FROM session_messages WHERE idempotency_key LIKE %s "
        "ORDER BY created_at",
        (f"qa-walk-silent:{execution_id}:%",),
    ).fetchall()
    return [row["body"] for row in rows]


def _state(conn: Any, execution_id: str) -> str:
    state = str(select_plan_execution(conn, execution_id, lock=False)["state"])
    conn.rollback()
    return state


@pytest.mark.parametrize("state", ["active", "walking"])
def test_a_walk_silent_twenty_minutes_mails_its_owner_once(
    test_db: Any, walk: str, state: str
) -> None:
    _silence(test_db, walk, 20, state=state)
    assert reap_stale_plan_executions(test_db, now=NOW) == []
    notices = _notices(test_db, walk)
    assert len(notices) == 1
    body = notices[0]
    assert f"execution {walk}" in body
    assert "has sent no heartbeat or owner tool activity for 20m" in body
    assert "aborts it at 2026-11-19T16:40Z" in body
    assert "`yoke qa mission host-command`" in body
    assert "`yoke qa plan abort " in body
    assert f"--execution-id {walk} --reason TEXT`" in body
    assert "coordination-claim release" not in body
    assert _state(test_db, walk) == state

    reap_stale_plan_executions(test_db, now=NOW + timedelta(minutes=2))
    assert len(_notices(test_db, walk)) == 1


def test_no_notice_below_the_line_or_after_a_fresh_heartbeat(
    test_db: Any, walk: str
) -> None:
    _silence(test_db, walk, 19)
    reap_stale_plan_executions(test_db, now=NOW)
    _silence(test_db, walk, 0)
    reap_stale_plan_executions(test_db, now=NOW)
    assert _notices(test_db, walk) == []


def test_a_parked_owner_gets_no_notice(test_db: Any, walk: str) -> None:
    test_db.execute(
        "UPDATE harness_sessions SET mode='parked', quiet_reason='hold' "
        "WHERE session_id=%s",
        (SESSION,),
    )
    _silence(test_db, walk, 25)
    reap_stale_plan_executions(test_db, now=NOW)
    assert _notices(test_db, walk) == []


@pytest.mark.parametrize("state", ["waiting", "awaiting_walk_review"])
def test_held_walks_get_no_notice(test_db: Any, walk: str, state: str) -> None:
    _silence(test_db, walk, 25, state=state)
    reap_stale_plan_executions(test_db, now=NOW)
    assert _notices(test_db, walk) == []
    assert _state(test_db, walk) == state


def test_a_new_silence_after_a_heartbeat_warns_again(test_db: Any, walk: str) -> None:
    _silence(test_db, walk, 20)
    reap_stale_plan_executions(test_db, now=NOW)
    later = NOW + timedelta(minutes=45)
    test_db.execute(
        "UPDATE qa_plan_executions SET heartbeat_at=%s WHERE id=%s",
        (instant_parameter(test_db, NOW + timedelta(minutes=5)), walk),
    )
    test_db.commit()
    reap_stale_plan_executions(test_db, now=NOW + timedelta(minutes=10))
    assert len(_notices(test_db, walk)) == 1
    reap_stale_plan_executions(test_db, now=later - timedelta(minutes=20))
    assert len(_notices(test_db, walk)) == 2


def test_a_walk_silent_past_thirty_minutes_is_still_aborted(
    test_db: Any, walk: str
) -> None:
    _silence(test_db, walk, 31)
    reaped = reap_stale_plan_executions(test_db, now=NOW)
    assert [entry["execution_id"] for entry in reaped] == [walk]
    assert reaped[0]["release_reason"] == "stale-heartbeat"
    assert _state(test_db, walk) == "aborted"


def test_the_roster_read_serves_each_owner_its_heartbeat_walks(
    test_db: Any, walk: str
) -> None:
    _silence(test_db, walk, 21, state="walking")
    served = silent_walks(test_db, [SESSION, "someone-else"])
    assert list(served) == [SESSION]
    (row,) = served[SESSION]
    assert row["execution_id"] == walk
    assert row["item"] == "YOK-5531"
    assert row["test_machine"] is None
    assert row["heartbeat_at"] is not None
    assert row["activity_at"] == NOW - timedelta(minutes=21)
    _silence(test_db, walk, 21, state="waiting")
    assert silent_walks(test_db, [SESSION]) == {}
    assert silent_walks(test_db, []) == {}


@pytest.mark.parametrize(
    "executor,tool,agent",
    [
        pytest.param("claude-code", "Read", None, id="claude-owner"),
        pytest.param("claude-code", "Read", "yoke-qa-walker", id="claude-child"),
        pytest.param("codex", "Bash", None, id="codex-owner-shell"),
        pytest.param("codex", "Bash", "yoke-qa-walker", id="codex-child-shell"),
        # Cursor's walker calls are recorded on the parent session.
        pytest.param("cursor", "Read", None, id="cursor-owner-or-folded-child"),
    ],
)
def test_recent_tool_activity_keeps_a_walk_live_until_the_activity_window_expires(
    test_db: Any, walk: str, executor: str, tool: str, agent: str | None
) -> None:
    test_db.execute(
        "UPDATE harness_sessions SET executor=%s WHERE session_id=%s",
        (executor, SESSION),
    )
    _silence(test_db, walk, 25, state="walking")
    envelope = {
        "session_id": SESSION,
        "executor": executor,
        "tool_name": tool,
        "tool_use_id": "walker-progress",
        "event_time": format_instant(NOW),
        "event_outcome": "completed",
    }
    if agent is not None:
        envelope["agent"] = agent
    for event in ("HarnessToolCallStarted", "HarnessToolCallCompleted"):
        apply_envelope_state(test_db, {**envelope, "event_name": event})
    test_db.commit()

    def alarm_age(now: datetime) -> list[int]:
        walks = silent_walks(test_db, [SESSION])[SESSION]
        owner = session_rows({
            "rows": [{"session_id": SESSION, "silent_walks": walks}]
        })[SESSION]
        return [minutes for _, minutes in stale_walks(owner, now)]

    assert reap_stale_plan_executions(test_db, now=NOW) == []
    assert _notices(test_db, walk) == []
    after_old_deadline = NOW + timedelta(minutes=6)
    assert reap_stale_plan_executions(test_db, now=after_old_deadline) == []
    assert alarm_age(after_old_deadline) == []

    warning_time = NOW + timedelta(minutes=20)
    assert reap_stale_plan_executions(test_db, now=warning_time) == []
    (notice,) = _notices(test_db, walk)
    assert "no heartbeat or owner tool activity for 20m" in notice
    assert "aborts it at 2026-11-19T17:00Z" in notice
    assert alarm_age(warning_time) == [20]

    reaped = reap_stale_plan_executions(test_db, now=NOW + timedelta(minutes=30))
    assert [entry["execution_id"] for entry in reaped] == [walk]
    assert _state(test_db, walk) == "aborted"
