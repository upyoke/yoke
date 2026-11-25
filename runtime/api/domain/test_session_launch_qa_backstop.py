"""A launcher can stop its walker and is told when the walker leaves work."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_plan_execution_authority_test_support import (
    _materialize_two_cases,
)
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_execution_authority import plan_execution_abort_authority
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    begin_plan_execution,
    select_plan_execution,
)
from yoke_core.domain.qa_plan_execution_stop import stop_plan_execution
from yoke_core.domain.session_launch_abandonment import settle_and_notify
from yoke_core.domain.session_launch_store import insert_instruction_message
from yoke_core.domain.sessions_render_end import end_session

OWNER, LAUNCHER, OTHER_LAUNCHER = "walker", "launcher", "other-launcher"
ITEM = 4909


def _message(conn, *, launch_id, sender, body):
    now = utc_now()
    message_id = str(uuid4())
    insert_instruction_message(
        conn, message_id=message_id, launch_id=launch_id, actor_id=1,
        session_id=sender, sender_surface=None, project_id=1,
        body=body, created_at=now, expires_at=now + timedelta(minutes=10),
    )
    return message_id


def _launch(conn, *, requester, worker, key):
    launch_id = str(uuid4())
    now = utc_now()
    message_id = _message(conn, launch_id=launch_id, sender=requester, body="Walk QA.")
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id,requester_actor_id,requester_session_id,project_id,requested_surface,"
        "selected_surface,message_id,idempotency_key,state,registered_session_id,created_at,deadline_at) "
        "VALUES (%s,1,%s,1,'codex-cli','codex-cli',%s,%s,'succeeded',%s,%s,%s)",
        (launch_id, requester, message_id, key, worker, now, now + timedelta(minutes=10)),
    )
    conn.execute(
        "UPDATE harness_sessions SET first_completed_work_at=%s WHERE session_id=%s",
        (now, worker),
    )
    conn.commit()
    return launch_id


@pytest.fixture
def execution(test_db):
    seed_qa_session(test_db, OWNER, LAUNCHER, OTHER_LAUNCHER, "other-worker")
    _materialize_two_cases(test_db, item_id=ITEM)
    return begin_plan_execution(
        test_db, item_id=ITEM, transition_id="implemented", actor_id="1", session_id=OWNER,
    )


def test_live_launcher_can_request_runner_stop_of_its_own_walker(test_db, execution):
    _launch(test_db, requester=LAUNCHER, worker=OWNER, key="qa-walk:own")
    _launch(test_db, requester=OTHER_LAUNCHER, worker="other-worker", key="qa-walk:other")

    def authority(session):
        return plan_execution_abort_authority(
            test_db, execution, item_id=ITEM, actor_id="1", session_id=session,
        )

    assert authority(LAUNCHER) == "launcher"
    with pytest.raises(QaPlanExecutionStateError, match="requires_steering"):
        authority(OTHER_LAUNCHER)
    result = stop_plan_execution(
        test_db, execution, actor_id="1", session_id=LAUNCHER, reason="cancel walk",
    )
    assert result["stop_request"]["outcome"] == "stop_requested"
    stored = select_plan_execution(test_db, execution["id"], lock=False)
    assert stored["state"] == "active"
    finished = stop_plan_execution(
        test_db, stored, actor_id="1", session_id=OWNER, reason="runner stopped",
    )
    assert finished["state"] == "aborted"
    assert "cancel walk" in finished["release_reason"]

    test_db.execute("UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s", (utc_now(), LAUNCHER))
    with pytest.raises(QaPlanExecutionStateError, match="requires_steering"):
        authority(LAUNCHER)


@pytest.mark.parametrize(
    ("key", "state", "reported", "notified"),
    [
        ("ordinary-launch", "waiting", False, True),
        ("qa-walk:missing-result", "completed", False, True),
        ("qa-walk:sent-result", "completed", True, False),
    ],
)
def test_session_end_reports_unsettled_qa_to_launcher(
    test_db, monkeypatch, execution, key, state, reported, notified,
):
    launch_id = _launch(test_db, requester=LAUNCHER, worker=OWNER, key=key)
    test_db.execute(
        "UPDATE qa_plan_executions SET state=%s WHERE id=%s", (state, execution["id"]),
    )
    if reported:
        message_id = _message(test_db, launch_id=launch_id, sender=OWNER, body="Walk result.")
        test_db.execute(
            "UPDATE session_messages SET idempotency_key=%s WHERE message_id=%s",
            (f"qa-walk-result:{execution['id']}", message_id),
        )
    test_db.commit()
    notices = []
    monkeypatch.setattr(
        "yoke_core.domain.session_message_service.send_message",
        lambda _conn, **message: notices.append(message),
    )

    end_session(test_db, OWNER)
    settle_and_notify(test_db, OWNER, end_reason="recheck")

    assert bool(notices) is notified
    if not notified:
        return
    notice = notices[0]
    assert notice["selector"].session_ids == [LAUNCHER]
    assert notice["idempotency_key"] == f"qa-walk-ended:{launch_id}"
    assert notices[1]["idempotency_key"] == notice["idempotency_key"]
    assert launch_id in notice["body"] and OWNER in notice["body"]
    assert execution["id"] in notice["body"]
    ref = render_item_ref(test_db, ITEM)
    assert f"yoke qa plan partitions --item {ref} --transition implemented" in notice["body"]
    assert f"yoke qa plan abort --item {ref} --execution-id" in notice["body"]
