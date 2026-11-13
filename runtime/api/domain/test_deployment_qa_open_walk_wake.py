"""A walk carried to a newer release is never told to wait or rerun."""

from __future__ import annotations

import pytest

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _claim,
    _project,
    seed_session,
)
from runtime.api.domain.deployment_run_target_takeover_test_support import (
    ITEM_QA_STAGE,
    NEW,
    OLD,
    PASSED,
    WAITING,
    _contains,
    _seed_new,
    _seed_old,
    _take_over,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_qa_dispatch_wait_notice import notify_stage_wait
from yoke_core.domain.deployment_qa_plan_ownership import open_walk_members
from yoke_core.domain.work_claim_targets import make_item_target

WALKER = "sess-carried-walker"


def _seed_takeover(conn, monkeypatch, walk=None) -> None:
    """Take OLD over; ``walk`` opens WAITING's walk on OLD first, so it moves."""
    _seed_old(conn, run_qa=False)
    _project(conn)
    for session_id, item_id in ((HOLDER_A, PASSED), (HOLDER_B, WAITING)):
        seed_session(conn, session_id)
        _claim(
            conn,
            session_id=session_id,
            target_kind="item",
            scope_json=make_item_target(item_id).scope_json(),
        )
    if walk is not None:
        _walk(conn, run_id=OLD, **walk)
    _seed_new(conn)
    _contains(monkeypatch)
    assert _take_over(conn) == OLD


def _walk(
    conn, *, state: str, ended: bool, stage: str = ITEM_QA_STAGE, run_id: str = NEW
) -> None:
    """WAITING's walk on ``run_id``, owned by WALKER."""
    seed_session(conn, WALKER)
    now = iso8601_now()
    conn.execute(
        "INSERT INTO qa_plan_executions (id,deployment_run_id,session_id,"
        "roster_digest,roster_json,state,created_at,heartbeat_at,"
        "deployment_stage,deployment_member_item_id) "
        "VALUES (%s,%s,%s,'d','[]',%s,%s,%s,%s,%s)",
        (f"exec-{state}", run_id, WALKER, state, now, now, stage, WAITING),
    )
    if ended:
        conn.execute(
            "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
            (now, WALKER),
        )
    conn.commit()


def _stage_wakes(conn, item_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT body FROM session_messages WHERE idempotency_key LIKE %s",
        (f"deployment-qa-stage-wait:{NEW}:{ITEM_QA_STAGE}:{item_id}:%",),
    ).fetchall()
    return [row["body"] for row in rows]


def _wake(conn, member: int) -> None:
    notify_stage_wait(
        conn,
        run_id=NEW,
        stage_name=ITEM_QA_STAGE,
        member=member,
        item_scoped=True,
        project_id=1,
        reasons="requirement pending",
        names_cases=True,
        target_tier="stage",
        revision="c" * 40,
        target_digest="digest",
        label="member",
    )


@pytest.mark.parametrize("state", ["walking", "awaiting_walk_review", "waiting"])
def test_open_walk_owner_gets_no_takeover_notice(test_db, monkeypatch, state):
    _seed_takeover(test_db, monkeypatch, walk={"state": state, "ended": False})

    assert open_walk_members(test_db, NEW, (WAITING,)) == {WAITING}
    assert _bodies(test_db, f"deployment-qa-moved:{NEW}:{WAITING}") == []
    assert len(_bodies(test_db, f"deployment-qa-moved:{NEW}:{PASSED}")) == 1


def test_ended_walk_owner_is_still_told_to_wait(test_db, monkeypatch):
    _seed_takeover(test_db, monkeypatch, walk={"state": "walking", "ended": True})

    [body] = _bodies(test_db, f"deployment-qa-moved:{NEW}:{WAITING}")
    assert "do not act on the predecessor's wake" in body


def test_stage_wake_skips_an_open_walk_and_records_nothing(
    test_db, monkeypatch, capsys
):
    _seed_takeover(test_db, monkeypatch)
    _walk(test_db, state="awaiting_walk_review", ended=False)

    _wake(test_db, WAITING)

    assert _stage_wakes(test_db, WAITING) == []
    assert "Staff it manually" not in capsys.readouterr().out

    # Once the owner ends, the next check wakes the member as usual.
    test_db.execute(
        "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
        (iso8601_now(), WALKER),
    )
    test_db.commit()
    _wake(test_db, WAITING)
    [body] = _stage_wakes(test_db, WAITING)
    assert "yoke qa plan run" in body


def test_stage_wake_reaches_a_member_whose_walk_owner_ended(test_db, monkeypatch):
    _seed_takeover(test_db, monkeypatch)
    _walk(test_db, state="walking", ended=True)

    _wake(test_db, WAITING)

    [body] = _stage_wakes(test_db, WAITING)
    assert "yoke qa plan run" in body


def test_open_walk_members_is_scoped_to_run_and_stage(test_db, monkeypatch):
    _seed_takeover(test_db, monkeypatch)
    _walk(test_db, state="walking", ended=False, stage="other-stage")

    assert open_walk_members(test_db, NEW, (PASSED, WAITING)) == {WAITING}
    assert open_walk_members(test_db, NEW, (WAITING,), stage="other-stage") == {
        WAITING
    }
    assert open_walk_members(test_db, NEW, (WAITING,), stage=ITEM_QA_STAGE) == set()
    assert open_walk_members(test_db, OLD, (WAITING,)) == set()
