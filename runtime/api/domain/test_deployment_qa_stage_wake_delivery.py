"""The item-scoped QA wait notice, delivered for real.

Exercises the actual recipient resolution and message insert — not a
mocked ``push_notice`` — so a wiring defect in claim/session lookup or in
:mod:`yoke_core.domain.session_message_service` itself would show up here.
The run-scoped counterpart lives in
``test_deployment_qa_stage_wake_run_scoped_delivery.py``, sharing these
same helpers, to keep each file under the authored line budget.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    seed_project,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_qa_stage_wake import notify_item_scoped_qa_wait
from yoke_core.domain.work_claim_targets import make_item_target

HOLDER_A = "sess-holder-a"
HOLDER_B = "sess-holder-b"

#: The actor id every ``seed_session`` row carries.
SESSION_ACTOR_ID = 2


def _project(conn: Any) -> None:
    """The project, plus the send-message role every seeded session's
    actor needs to reach another session in it."""
    seed_project(conn, PROJECT_YOKE, "yoke")
    seed_roles_and_permissions(conn)
    grant_actor_project_role(
        conn, actor_id=SESSION_ACTOR_ID, project_id=PROJECT_YOKE, role_name=ROLE_OWNER
    )


def seed_session(conn: Any, session_id: str, project_id: int = PROJECT_YOKE) -> None:
    """A session whose route resolves ``messageable`` for real delivery.

    ``coordination_claim_test_support.seed_session`` leaves
    ``executor_surface``/``executor_version`` unset, which is fine for a
    deploy-lock claim's own identity but unmessageable — a Fleet send
    reads those columns for a real hook route, so this file's sessions
    need the shape :mod:`test_session_message_support` already proves is
    routable.
    """
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions (session_id,project_id,actor_id,workspace,"
        "executor,provider,executor_surface,executor_version,machine_id,"
        "execution_lane,last_heartbeat,offered_at) VALUES "
        "(%s,%s,%s,'/tmp',%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            session_id,
            project_id,
            SESSION_ACTOR_ID,
            "claude-code",
            "anthropic",
            "claude-cli",
            "2.1.238",
            "m-wake-delivery-test",
            "direct",
            now,
            now,
        ),
    )
    conn.commit()


def _claim(conn: Any, *, session_id: str, target_kind: str, scope_json: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO work_claims (session_id,target_kind,scope,claimed_at,"
        "last_heartbeat) VALUES (%s,%s,%s,%s,%s)",
        (session_id, target_kind, scope_json, now, now),
    )
    conn.commit()


def _recipients(conn: Any, idempotency_key: str) -> list[str]:
    rows = conn.execute(
        "SELECT r.session_id FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id = m.message_id "
        "WHERE m.idempotency_key = %s",
        (idempotency_key,),
    ).fetchall()
    return [row["session_id"] if hasattr(row, "keys") else row[0] for row in rows]


def _bodies(conn: Any, idempotency_key: str) -> list[str]:
    rows = conn.execute(
        "SELECT body FROM session_messages WHERE idempotency_key = %s",
        (idempotency_key,),
    ).fetchall()
    return [row["body"] if hasattr(row, "keys") else row[0] for row in rows]


def test_item_holder_receives_a_real_message(test_db: Any) -> None:
    _project(test_db)
    item_id = 9701
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )

    result = notify_item_scoped_qa_wait(
        test_db,
        run_id="run-wd-1",
        stage_name="item-qa",
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="awaiting agent verdict",
        target_tier="persistent",
        revision="a" * 40,
    )

    assert result in ("delivered", "undelivered")
    from yoke_core.domain.deployment_qa_stage_wake import stage_wait_idempotency_key

    key = stage_wait_idempotency_key("run-wd-1", "item-qa", item_id)
    assert _recipients(test_db, key) == [HOLDER_A]
    [body] = _bodies(test_db, key)
    assert "run-wd-1" in body
    assert "item-qa" in body
    assert "persistent" in body
    assert ("a" * 12) in body
    assert "awaiting agent verdict" in body


def test_no_holder_and_no_steering_addresses_nobody(test_db: Any) -> None:
    _project(test_db)
    item_id = 9702
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")

    result = notify_item_scoped_qa_wait(
        test_db,
        run_id="run-wd-2",
        stage_name="item-qa",
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="awaiting agent verdict",
    )

    assert result == ""
    from yoke_core.domain.deployment_qa_stage_wake import stage_wait_idempotency_key

    assert _recipients(test_db, stage_wait_idempotency_key("run-wd-2", "item-qa", item_id)) == []


def test_a_later_holder_change_does_not_get_a_second_notice(test_db: Any) -> None:
    """Documents the existing idempotency contract for this new call site.

    The notice is keyed by (run, stage, item), not by holder, so once it
    has been sent once the same key's later checks reuse that first
    message even after the claim moves to a different session -- exactly
    how :func:`merge_queue_landing_notice.push_notice` already behaves for
    every other caller.
    """
    _project(test_db)
    item_id = 9703
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    from yoke_core.domain.deployment_qa_stage_wake import stage_wait_idempotency_key

    key = stage_wait_idempotency_key("run-wd-3", "item-qa", item_id)

    # No holder yet: nothing is sent, so the key is not consumed.
    assert (
        notify_item_scoped_qa_wait(
            test_db,
            run_id="run-wd-3",
            stage_name="item-qa",
            item_id=item_id,
            project_id=PROJECT_YOKE,
            reasons="awaiting agent verdict",
        )
        == ""
    )
    assert _recipients(test_db, key) == []

    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    notify_item_scoped_qa_wait(
        test_db,
        run_id="run-wd-3",
        stage_name="item-qa",
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="awaiting agent verdict",
    )
    assert _recipients(test_db, key) == [HOLDER_A]

    test_db.execute(
        "UPDATE work_claims SET released_at=%s WHERE session_id=%s",
        (iso8601_now(), HOLDER_A),
    )
    test_db.commit()
    seed_session(test_db, HOLDER_B)
    _claim(
        test_db,
        session_id=HOLDER_B,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    notify_item_scoped_qa_wait(
        test_db,
        run_id="run-wd-3",
        stage_name="item-qa",
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="different reasons now",
    )

    assert _recipients(test_db, key) == [HOLDER_A]


def test_repeat_dispatch_after_reasons_change_does_not_collide(test_db: Any) -> None:
    """A stage rechecked while still waiting recomputes ``reasons`` fresh
    each time; the notice's identity (run, stage, item) does not depend on
    that text, so a second check with different wording is a dedupe, not
    an ``idempotency_conflict`` raise."""
    _project(test_db)
    item_id = 9704
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    from yoke_core.domain.deployment_qa_stage_wake import stage_wait_idempotency_key

    key = stage_wait_idempotency_key("run-wd-3b", "item-qa", item_id)

    notify_item_scoped_qa_wait(
        test_db,
        run_id="run-wd-3b",
        stage_name="item-qa",
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="2 of 3 requirements outstanding",
    )
    # Does not raise even though the text below differs from the first call.
    notify_item_scoped_qa_wait(
        test_db,
        run_id="run-wd-3b",
        stage_name="item-qa",
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="1 of 3 requirements outstanding",
    )

    assert _recipients(test_db, key) == [HOLDER_A]
    [body] = _bodies(test_db, key)
    assert "2 of 3 requirements outstanding" in body


def test_a_later_deployment_attempt_gets_its_own_fresh_notice(test_db: Any) -> None:
    """A new deploy attempt runs under a new ``run_id``, which is already a
    distinct key -- no separate attempt-identity concept is needed for a
    fresh notice to go out."""
    _project(test_db)
    item_id = 9705
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    from yoke_core.domain.deployment_qa_stage_wake import stage_wait_idempotency_key

    first_key = stage_wait_idempotency_key("run-attempt-1", "item-qa", item_id)
    second_key = stage_wait_idempotency_key("run-attempt-2", "item-qa", item_id)

    notify_item_scoped_qa_wait(
        test_db,
        run_id="run-attempt-1",
        stage_name="item-qa",
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="first attempt's evidence still missing",
    )
    notify_item_scoped_qa_wait(
        test_db,
        run_id="run-attempt-2",
        stage_name="item-qa",
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="second attempt's evidence still missing",
    )

    assert _recipients(test_db, first_key) == [HOLDER_A]
    assert _recipients(test_db, second_key) == [HOLDER_A]
    [first_body] = _bodies(test_db, first_key)
    [second_body] = _bodies(test_db, second_key)
    assert "first attempt's evidence still missing" in first_body
    assert "second attempt's evidence still missing" in second_body
