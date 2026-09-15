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

import json
from typing import Any

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    SESSION_ACTOR_ID,
    _claim,
    _project,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    ROLE_OWNER,
    grant_actor_org_role,
    grant_actor_project_role,
)
from yoke_core.domain.deployment_delivery_done_notice import (
    delivery_done_idempotency_key,
    notify_delivery_done,
)
from yoke_core.domain.deployment_flow_versioning import cmd_create
from yoke_core.domain.work_claim_targets import make_item_target

LINEAGE = "d" * 40
OWNER_ACTOR_ID = 9901


def _owner(conn: Any, project_id: int = 1) -> int:
    """A human member of the project, distinct from the claim holder's actor."""
    conn.execute(
        "INSERT INTO actors(id,kind,name,created_at) VALUES "
        "(%s,'human','Release Owner','2026-09-14T00:00:00Z') "
        "ON CONFLICT(id) DO NOTHING",
        (OWNER_ACTOR_ID,),
    )
    grant_actor_project_role(
        conn,
        actor_id=OWNER_ACTOR_ID,
        project_id=project_id,
        role_name=ROLE_OWNER,
    )
    # Addressing a human member resolves through shared organization
    # membership, so the owner needs its org role too.
    for org_id in _org_ids(conn, project_id):
        grant_actor_org_role(
            conn, actor_id=OWNER_ACTOR_ID, org_id=org_id, role_name=ROLE_ADMIN
        )
    conn.commit()
    return OWNER_ACTOR_ID


def _org_ids(conn: Any, project_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT org_id FROM projects WHERE id=%s", (int(project_id),)
    ).fetchall()
    return [int(row["org_id"]) for row in rows if row["org_id"] is not None]


def _environment(conn: Any) -> int:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'stage','https://stage.example.test','{}',%s FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO UPDATE SET url=EXCLUDED.url",
        ("2026-09-14T00:00:00Z",),
    )
    return int(
        conn.execute(
            "SELECT id FROM environments WHERE project_id=1 AND name='stage'"
        ).fetchone()["id"]
    )


def _run(
    conn: Any,
    run_id: str,
    item_id: int,
    *,
    status: str = "succeeded",
    intent: str = "final",
    target_tier: str = "persistent",
    with_environment: bool = True,
    observed_target: str = "",
) -> None:
    environment_id = _environment(conn) if with_environment else None
    flow_id = f"flow-{run_id}"
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        json.dumps([{"name": "deploy", "step_runner": "auto"}]),
        status="disabled",
    )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "target_tier,target_environment_id,current_stage,created_at,completed_at) "
        "VALUES (%s,1,%s,%s,%s,%s,%s,'complete',%s,%s)",
        (
            run_id,
            flow_id,
            LINEAGE,
            status,
            target_tier,
            environment_id,
            "2026-09-14T00:00:00Z",
            "2026-09-14T00:05:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,delivery_intent) "
        "VALUES (%s,%s,%s,%s)",
        (run_id, item_id, "2026-09-14T00:00:00Z", intent),
    )
    if observed_target:
        conn.execute(
            "INSERT INTO deployment_stage_receipts(run_id,stage_name,"
            "attempt_number,correlation_id,target_kind,target_name,status,"
            "observed_release_lineage,executor,created_at,completed_at) VALUES "
            "(%s,'deploy',1,%s,'persistent_environment',%s,'ready',%s,'test',"
            "%s,%s)",
            (
                run_id,
                f"{run_id}-deploy-1",
                observed_target,
                LINEAGE,
                "2026-09-14T00:00:00Z",
                "2026-09-14T00:04:00Z",
            ),
        )
    conn.commit()


def _inbox(conn: Any, idempotency_key: str) -> list[tuple[int, str]]:
    """Every human-Inbox recipient row for one notice, with its body."""
    rows = conn.execute(
        "SELECT r.actor_id, m.body FROM session_messages m "
        "JOIN actor_message_recipients r ON r.message_id = m.message_id "
        "WHERE m.idempotency_key = %s ORDER BY r.actor_id",
        (idempotency_key,),
    ).fetchall()
    return [(int(row["actor_id"]), str(row["body"])) for row in rows]


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
