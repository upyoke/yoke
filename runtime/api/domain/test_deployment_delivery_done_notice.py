"""The item's OWNER learns a delivery completed, once, with its destination.

Real owner resolution and a real Inbox insert. The recipient is the human
member ``items.owner`` names, which these cases hold apart from the agent
holding the work claim: a different actor's session holds that claim in
the first test, and the notice still reaches the owner and only the
owner. What the notice must not do matters as much: a merge-only item has
no delivery to announce, a failed run is not one, an unresolvable owner
is reported rather than redirected, and nothing here is a gate.
"""

from __future__ import annotations

from runtime.api.domain.deployment_delivery_done_notice_test_support import (
    LINEAGE as LINEAGE,
    OWNER_ACTOR_ID as OWNER_ACTOR_ID,
    _environment as _environment,
    _inbox as _inbox,
    _org_ids as _org_ids,
    _owner as _owner,
    _run as _run,
)


from typing import Any

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    SESSION_ACTOR_ID,
    _claim,
    _project,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_delivery_done_notice import (
    delivery_done_idempotency_key,
    notify_delivery_done,
)
from yoke_core.domain.work_claim_targets import make_item_target


def _owned_item(conn: Any, item_id: int, *, workflow_id: str = "issue") -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id=workflow_id,
        owner=str(OWNER_ACTOR_ID),
    )


def test_the_owner_is_told_even_though_an_agent_holds_the_claim(
    test_db: Any,
) -> None:
    _project(test_db)
    _owner(test_db)
    item_id = 9820
    _owned_item(test_db, item_id)
    _run(test_db, "run-delivered", item_id, observed_target="stage")
    # A different actor's session holds the item's work claim.
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    assert SESSION_ACTOR_ID != OWNER_ACTOR_ID

    result = notify_delivery_done(test_db, item_id=item_id)
    test_db.commit()

    assert result["delivery"] == "notified"
    assert result["owner_actor_id"] == OWNER_ACTOR_ID
    inbox = _inbox(test_db, delivery_done_idempotency_key(item_id, "run-delivered"))
    assert [actor_id for actor_id, _body in inbox] == [OWNER_ACTOR_ID]
    body = inbox[0][1]
    assert "is done" in body
    assert "to stage" in body
    assert LINEAGE[:12] in body
    assert "run-delivered" in body
    # Informational by construction: it says so and asks for nothing.
    assert "nothing to approve" in body
    # And no agent session was addressed by this notice at all.
    sessions = test_db.execute(
        "SELECT COUNT(*) FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id = r.message_id "
        "WHERE m.idempotency_key = %s",
        (delivery_done_idempotency_key(item_id, "run-delivered"),),
    ).fetchone()[0]
    assert int(sessions) == 0


def test_a_repeat_announcement_is_one_notice(test_db: Any) -> None:
    """Existing dedupe, not a new retry framework."""
    _project(test_db)
    _owner(test_db)
    item_id = 9821
    _owned_item(test_db, item_id)
    _run(test_db, "run-repeat", item_id, observed_target="stage")

    notify_delivery_done(test_db, item_id=item_id)
    test_db.commit()
    notify_delivery_done(test_db, item_id=item_id)
    test_db.commit()

    assert len(_inbox(test_db, delivery_done_idempotency_key(item_id, "run-repeat"))) == 1


def test_an_item_with_no_delivery_announces_nothing(test_db: Any) -> None:
    _project(test_db)
    _owner(test_db)
    item_id = 9822
    _owned_item(test_db, item_id, workflow_id="dash")

    result = notify_delivery_done(test_db, item_id=item_id)

    assert result == {
        "delivery": "",
        "run_id": "",
        "reason": "no succeeded deployment run is attached to this item",
    }


def test_a_failed_run_is_not_a_delivery(test_db: Any) -> None:
    _project(test_db)
    _owner(test_db)
    item_id = 9823
    _owned_item(test_db, item_id)
    _run(test_db, "run-failed", item_id, status="failed")

    assert notify_delivery_done(test_db, item_id=item_id)["delivery"] == ""


def test_an_unresolvable_owner_is_reported_not_redirected(test_db: Any) -> None:
    """A legacy free-text owner is not an actor, and not an agent either."""
    _project(test_db)
    _owner(test_db)
    item_id = 9824
    insert_item(
        test_db, id=item_id, project_sequence=item_id, workflow_id="issue", owner="ben"
    )
    _run(test_db, "run-ownerless", item_id, observed_target="stage")
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )

    result = notify_delivery_done(test_db, item_id=item_id)

    assert result["delivery"] == ""
    assert "no human organization member" in result["reason"]
    assert _inbox(test_db, delivery_done_idempotency_key(item_id, "run-ownerless")) == []


def test_a_progress_delivery_names_itself_as_one(test_db: Any) -> None:
    """A Blitz slice's run is a delivery, not the item's final completion."""
    _project(test_db)
    _owner(test_db)
    item_id = 9825
    _owned_item(test_db, item_id, workflow_id="blitz")
    _run(test_db, "run-progress", item_id, intent="progress", observed_target="stage")

    notify_delivery_done(test_db, item_id=item_id)
    test_db.commit()

    body = _inbox(test_db, delivery_done_idempotency_key(item_id, "run-progress"))[0][1]
    assert "Delivery completed" in body
    assert "Final delivery" not in body


def test_the_destination_is_the_one_observed_not_the_one_configured(
    test_db: Any,
) -> None:
    """A multi-environment journey delivers past the run's configured aim."""
    _project(test_db)
    _owner(test_db)
    item_id = 9826
    _owned_item(test_db, item_id)
    _run(test_db, "run-promoted", item_id, observed_target="production")

    notify_delivery_done(test_db, item_id=item_id)
    test_db.commit()

    body = _inbox(test_db, delivery_done_idempotency_key(item_id, "run-promoted"))[0][1]
    assert "to production" in body
    assert "to stage" not in body


def test_an_unobserved_destination_falls_back_to_the_target_tier(
    test_db: Any,
) -> None:
    _project(test_db)
    _owner(test_db)
    item_id = 9827
    _owned_item(test_db, item_id)
    _run(
        test_db,
        "run-tierless",
        item_id,
        with_environment=False,
        target_tier="ephemeral",
    )

    notify_delivery_done(test_db, item_id=item_id)
    test_db.commit()

    body = _inbox(test_db, delivery_done_idempotency_key(item_id, "run-tierless"))[0][1]
    assert "to ephemeral" in body
