"""Held release plan groups notify every owing item's owner without stale wakes."""

import pytest

from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS, RUN, SLUG, _begin, _pass_group, _seed,
)
from runtime.api.domain.test_deployment_qa_plan_group_scenarios import (
    _dispatch, _form, _manual_plan,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A, HOLDER_B, _bodies, _claim, _project, _recipients, seed_session,
)
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_core.domain.deployment_qa_plan_group_dispatch import plan_groups_wait_key
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_stage_wake import (
    notify_item_scoped_qa_wait, stage_wait_idempotency_key,
)
from yoke_core.domain.work_claim_targets import make_item_target, make_steering_target


def _setup(conn, *, manual=True):
    plan_id = _seed(conn)
    if manual:
        _manual_plan(conn, plan_id)
    _project(conn)
    for session in (HOLDER_A, HOLDER_B, "group-steering"):
        seed_session(conn, session)
    for member, session in zip(MEMBERS[:2], (HOLDER_A, HOLDER_B)):
        _claim(conn, session_id=session, target_kind="item",
               scope_json=make_item_target(member).scope_json())
    _claim(conn, session_id="group-steering", target_kind="steering",
           scope_json=make_steering_target(1).scope_json())
    conn.execute("UPDATE harness_sessions SET mode='parked' WHERE session_id=%s", (HOLDER_A,))
    conn.commit()
    _form(conn)
    return run_groups(conn, RUN, "item-qa")[0]


def _key(group, member):
    return stage_wait_idempotency_key(RUN, "item-qa", member, f"plan-group-{group.group_id}")


def _messages(conn):
    return conn.execute(
        "SELECT idempotency_key,cancelled_at FROM session_messages "
        "WHERE idempotency_key LIKE %s ORDER BY idempotency_key",
        (f"deployment-qa-stage-wait:{RUN}:item-qa:%",),
    ).fetchall()


@pytest.mark.parametrize("manual", [True, False], ids=["manual", "walk-review"])
def test_held_group_notifies_each_owing_owner_and_driver_once(test_db, manual):
    group = _setup(test_db, manual=manual)
    if not manual:
        execution = _begin(test_db)
        test_db.execute(
            "UPDATE qa_plan_executions SET state='awaiting_walk_review' WHERE id=%s",
            (execution["id"],),
        )
        test_db.commit()

    assert _dispatch(test_db)
    assert _dispatch(test_db)

    assert len(_messages(test_db)) == len(MEMBERS) + 1
    for member, recipient in zip(MEMBERS, (HOLDER_A, HOLDER_B, "group-steering")):
        key = _key(group, member)
        assert _recipients(test_db, key) == [recipient]
        [body] = _bodies(test_db, key)
        assert f"Deployment run {RUN} stage 'item-qa'" in body
        assert f"plan {SLUG} (group {group.group_id}) owed by {member}" in body
        for requirement_id in group.requirement_ids:
            assert f"requirement #{requirement_id} (case command-smoke)" in body
        assert f"qa plan run --deployment-run-id {RUN} --stage item-qa --plan {SLUG}" in body
        assert "waive or remove the case" in body
    assert "claim holder" in _bodies(test_db, _key(group, MEMBERS[0]))[0]
    assert "project steering seat (its claim holder is gone)" in _bodies(
        test_db, _key(group, MEMBERS[2])
    )[0]
    assert _recipients(test_db, plan_groups_wait_key(RUN, "item-qa", [group])) == [DRIVER_SESSION]


def test_group_notice_does_not_suppress_member_wait_with_same_target(test_db):
    group = _setup(test_db)
    _dispatch(test_db)

    notify_item_scoped_qa_wait(
        test_db, run_id=RUN, stage_name="item-qa", item_id=MEMBERS[0],
        project_id=1, reasons="member's own case awaits review", names_cases=True,
        target_digest=group.digest,
    )

    own_key = stage_wait_idempotency_key(RUN, "item-qa", MEMBERS[0], group.digest)
    assert _recipients(test_db, own_key) == [HOLDER_A]
    assert _recipients(test_db, _key(group, MEMBERS[0])) == [HOLDER_A]
    assert len(_messages(test_db)) == len(MEMBERS) + 2


def test_closing_group_cancels_group_notices_and_preserves_member_wait(test_db):
    group = _setup(test_db)
    _dispatch(test_db)
    notify_item_scoped_qa_wait(
        test_db, run_id=RUN, stage_name="item-qa", item_id=MEMBERS[0],
        project_id=1, reasons="member's own case awaits review", names_cases=True,
        target_digest=group.digest,
    )

    _pass_group(test_db)

    assert run_groups(test_db, RUN, "item-qa")[0].closed
    own_key = stage_wait_idempotency_key(RUN, "item-qa", MEMBERS[0], group.digest)
    messages = dict(_messages(test_db))
    assert messages[own_key] is None
    for key in [*(_key(group, member) for member in MEMBERS),
                plan_groups_wait_key(RUN, "item-qa", [group])]:
        assert messages[key] is not None
        assert test_db.execute(
            "SELECT r.state FROM session_message_recipients r JOIN session_messages m "
            "ON m.message_id=r.message_id WHERE m.idempotency_key=%s", (key,),
        ).fetchone()[0] == "cancelled"


def test_automatic_only_group_sends_no_wait_notice(test_db):
    _setup(test_db, manual=False)
    assert _dispatch(test_db)
    assert _messages(test_db) == []
