"""Cancelled sender and deployment-driver notices can be sent again by intent."""

from datetime import timedelta

import pytest

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import (
    cancel_message_rows,
    insert_message,
    message_details,
)
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


@pytest.mark.parametrize("engine", [False, True])
def test_cancelled_message_does_not_dedupe_but_uncancelled_retry_does(engine):
    conn = message_connection()

    def send():
        if engine:
            details, created = insert_message(
                conn,
                sender_actor_id=None,
                sender_session_id=None,
                sender_surface=None,
                body="QA is owed",
                selector_snapshot={},
                idempotency_key="same-key",
                created_at=NOW,
                expires_at=NOW + timedelta(hours=1),
                recipients=[],
                actor_recipients=[],
                wake_after_by_owner={},
            )
            conn.commit()
            return details["message_id"], not created
        result = send_message(
            conn,
            actor_id=10,
            sender_session_id="s1",
            selector=selector(session_ids=["s2"]),
            body="QA is owed",
            idempotency_key="same-key",
            now=NOW,
        )
        return result["message_id"], result["deduplicated"]

    first, _ = send()
    cancel_message_rows(
        conn,
        message_id=first,
        actor_id=10,
        reason="test cancellation",
        cancelled_at=NOW,
    )
    conn.commit()
    second, duplicate = send()
    assert second != first and duplicate is False
    assert send() == (second, True)
    assert message_details(conn, first)["cancelled_at"] is not None
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 2


def test_deployment_driver_resends_cancelled_notice_at_its_next_check(test_db):
    from yoke_core.domain.deployment_qa_stage_wake import (
        notify_item_scoped_qa_wait,
        stage_wait_idempotency_key,
    )
    from yoke_core.domain.work_claim_targets import make_item_target
    from runtime.api.domain.test_deployment_qa_stage_dispatch_wake import _run, _member
    from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
        HOLDER_A,
        _project,
        _claim,
        seed_session,
    )

    _project(test_db)
    run_id, item_id = "run-cancelled-wake", 9630
    _run(test_db, run_id)
    _member(test_db, run_id, item_id)
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    args = dict(
        run_id=run_id,
        stage_name="item-qa",
        item_id=item_id,
        project_id=1,
        reasons="QA is owed",
        names_cases=True,
    )
    notify_item_scoped_qa_wait(test_db, **args)
    key = stage_wait_idempotency_key(run_id, "item-qa", item_id)
    first = test_db.execute(
        "SELECT message_id FROM session_messages WHERE idempotency_key=%s", (key,)
    ).fetchone()[0]
    cancel_message_rows(
        test_db,
        message_id=first,
        actor_id=1,
        reason="test cancellation",
        cancelled_at=NOW,
    )
    test_db.commit()
    notify_item_scoped_qa_wait(test_db, **args)
    notify_item_scoped_qa_wait(test_db, **args)
    rows = test_db.execute(
        "SELECT m.message_id,m.cancelled_at,r.state FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id=m.message_id WHERE m.idempotency_key=%s",
        (key,),
    ).fetchall()
    assert len(rows) == 2
    assert [(row[0], row[2]) for row in rows if row[1] is not None] == [
        (first, "cancelled")
    ]
    assert len([row for row in rows if row[1] is None and row[2] == "pending"]) == 1
