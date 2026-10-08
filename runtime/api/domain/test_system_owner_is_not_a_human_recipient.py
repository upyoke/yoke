"""A numeric system actor is not an item owner and not a human recipient.

``items.owner`` may hold that actor's id. Resolution answers none, the
delivery notice is not sent, and addressing the same id as a person is
refused. Nothing here sends Fleet mail.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_delivery_done_notice import (
    _inbox,
    _owner,
    _project,
    _run,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    _claim,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.session_control.recipient_selector import RecipientSelector
from yoke_core.domain.actor_message_recipients import resolve_actor_recipients
from yoke_core.domain.actors import seed_system_actor
from yoke_core.domain.deployment_delivery_done_notice import (
    delivery_done_idempotency_key,
    notify_delivery_done,
)
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.work_claim_targets import make_item_target

ITEM_ID = 9828


def _system_owner(conn: Any) -> int:
    actor_id = seed_system_actor(conn, "delivery-notice-walker")
    insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=ITEM_ID,
        workflow_id="issue",
        owner=str(actor_id),
    )
    conn.commit()
    return actor_id


def test_a_numeric_system_owner_is_not_notified(test_db: Any) -> None:
    """The id is numeric and still not a person, so nobody is told."""
    _project(test_db)
    human_sender = _owner(test_db)
    system_actor_id = _system_owner(test_db)
    _run(test_db, "run-system-owner", ITEM_ID, observed_target="stage")
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(ITEM_ID).scope_json(),
    )

    result = notify_delivery_done(test_db, item_id=ITEM_ID)

    assert result["delivery"] == ""
    assert result["run_id"] == "run-system-owner"
    assert "no human organization member" in result["reason"]
    assert (
        _inbox(test_db, delivery_done_idempotency_key(ITEM_ID, "run-system-owner"))
        == []
    )
    try:
        resolve_actor_recipients(
            test_db,
            RecipientSelector(actors=[str(system_actor_id)]),
            sender_actor_id=human_sender,
        )
    except SessionMessageError as exc:
        assert exc.code == "actor_recipient_not_human"
    else:
        raise AssertionError("system actor was accepted as a human recipient")
