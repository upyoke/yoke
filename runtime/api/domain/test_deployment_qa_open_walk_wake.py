"""A walk carried to a newer release is never told to wait or rerun."""

from __future__ import annotations

from types import SimpleNamespace

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
from yoke_core.domain.deployment_qa_plan_ownership import (
    open_walk_members,
    plan_only_members,
)
from yoke_core.domain.merge_queue_landing_notice import addressable_items
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.work_claim_targets import make_item_target

WALKER = "sess-carried-walker"


def _seed_takeover(conn, monkeypatch, walk=None, *, expected_notice=None) -> None:
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
    if expected_notice is not None:
        _assert_takeover_notice(conn, monkeypatch, expected_notice)
        return
    assert _take_over(conn) == OLD


def _assert_takeover_notice(conn, monkeypatch, member: int) -> None:
    """Observe the actual send so a missing row explains where delivery stopped."""
    from yoke_core.domain import deployment_qa_takeover_notice

    ids = (member,)
    project_id = 1
    assert member in addressable_items(conn, item_ids=ids, project_id=project_id), (
        f"Member {member} is not addressable before takeover"
    )
    assert member not in plan_only_members(conn, OLD, ids), (
        f"Member {member} is plan-only before takeover"
    )
    assert member not in open_walk_members(conn, OLD, ids), (
        f"Member {member} has a live walk before takeover"
    )

    push = deployment_qa_takeover_notice.deployment_run_driver_notice.push_member_notice
    attempts = {}

    def observe(*args, **kwargs):
        item_id = kwargs["item_id"]
        try:
            outcome = push(*args, **kwargs)
        except SessionMessageError as exc:
            attempts[item_id] = f"message refused: {exc}"
            raise
        attempts[item_id] = (
            f"send returned {outcome!r} without writing the notice"
            if outcome
            else "send resolved no recipient"
        )
        return outcome

    with monkeypatch.context() as patch:
        patch.setattr(
            deployment_qa_takeover_notice,
            "deployment_run_driver_notice",
            SimpleNamespace(push_member_notice=observe),
        )
        assert _take_over(conn) == OLD

    if _bodies(conn, f"deployment-qa-moved:{NEW}:{member}"):
        return
    if member in attempts:
        pytest.fail(f"Takeover notice missing for member {member}: {attempts[member]}")
    assert member not in plan_only_members(conn, NEW, ids), (
        f"Takeover filtered plan-only member {member}"
    )
    assert member not in open_walk_members(conn, NEW, ids), (
        f"Takeover filtered member {member} with a live walk"
    )
    assert member in addressable_items(conn, item_ids=ids, project_id=project_id), (
        f"Takeover could not address member {member}"
    )
    assert member not in deployment_qa_takeover_notice.recheck_holding_members(
        conn, new_id=NEW, item_ids=ids, project_id=project_id
    ), f"Takeover filtered member {member} whose holder has a scheduled recheck"
    pytest.fail(f"Takeover never attempted a notice for eligible member {member}")


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
    _seed_takeover(
        test_db,
        monkeypatch,
        walk={"state": state, "ended": False},
        expected_notice=PASSED,
    )

    assert open_walk_members(test_db, NEW, (WAITING,)) == {WAITING}
    assert _bodies(test_db, f"deployment-qa-moved:{NEW}:{WAITING}") == []
    assert len(_bodies(test_db, f"deployment-qa-moved:{NEW}:{PASSED}")) == 1


@pytest.mark.parametrize("state", ["walking", "awaiting_walk_review", "waiting"])
def test_takeover_carries_an_open_walk_intact_and_the_receipt_names_it(
    test_db, monkeypatch, state
):
    from yoke_core.domain.deployment_run_create_receipt import continuation_facts

    _seed_takeover(test_db, monkeypatch, walk={"state": state, "ended": False})
    test_db.commit()

    row = test_db.execute(
        "SELECT id,state,deployment_run_id,session_id,deployment_member_item_id "
        "FROM qa_plan_executions WHERE id=%s",
        (f"exec-{state}",),
    ).fetchone()
    assert dict(row) == {
        "id": f"exec-{state}",
        "state": state,
        "deployment_run_id": NEW,
        "session_id": WALKER,
        "deployment_member_item_id": WAITING,
    }
    assert _bodies(test_db, f"deployment-qa-moved:{NEW}:{WAITING}") == []
    facts = continuation_facts(NEW)
    assert facts["supersedes_run_id"] == OLD
    assert facts["carried_execution_ids"] == [f"exec-{state}"]


def test_ended_walk_owner_is_still_told_to_wait(test_db, monkeypatch):
    _seed_takeover(
        test_db,
        monkeypatch,
        walk={"state": "walking", "ended": True},
        expected_notice=WAITING,
    )

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
