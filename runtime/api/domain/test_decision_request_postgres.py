"""Postgres authority proof for the additive decision-request substrate."""

from __future__ import annotations

from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
    pending_requests_for_actor,
)
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)


def test_postgres_schema_authority_and_transactional_resolution(test_db):
    create_decision_request_tables(test_db)
    org_id = 9001
    project_id = 9010
    test_db.execute(
        "INSERT INTO organizations (id, slug, name, created_at) "
        "VALUES (%s, 'inbox-proof', 'Inbox proof', '2026-07-26T00:00:00Z')",
        (org_id,),
    )
    test_db.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, created_at, org_id) "
        "VALUES (%s, 'inbox-proof', 'Inbox proof', 'IBX', "
        "'2026-07-26T00:00:00Z', %s)",
        (project_id, org_id),
    )
    actor_ids = [9101, 9102]
    for actor_id, label in zip(actor_ids, ("originator", "owner")):
        test_db.execute(
            "INSERT INTO actors (id, kind, created_at) "
            "VALUES (%s, 'human', '2026-07-26T00:00:00Z')",
            (actor_id,),
        )
        test_db.execute(
            "INSERT INTO actor_labels "
            "(actor_id, surface, label, created_at) "
            "VALUES (%s, 'display', %s, '2026-07-26T00:00:00Z')",
            (actor_id, label),
        )
    role_id = test_db.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (9201, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
        "RETURNING id"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, %s, %s, '2026-07-26T00:00:00Z')",
        (actor_ids[1], project_id, role_id),
    )
    test_db.commit()

    request, created = create_decision_request(
        test_db, kind="lifecycle_transition_approval",
        subject_type="item_transition", subject_key="17:done",
        project_id=project_id, originator_actor_id=actor_ids[0],
        role_authorities=[RoleAuthority("project", project_id, "owner")],
        subject_context={"public_ref": "IBX-17", "transition": "done"},
    )
    assert created is True
    assert pending_requests_for_actor(test_db, actor_ids[1])[0]["id"] == (
        request["id"]
    )
    resolved = resolve_decision_request(
        test_db, request["id"], actor_id=actor_ids[1], action="approve",
    )
    assert resolved["status"] == "resolved"
    notification = test_db.execute(
        "SELECT notification_kind FROM addressed_event_deliveries "
        "WHERE actor_id=%s",
        (actor_ids[0],),
    ).fetchone()
    assert notification[0] == "decision_request_resolved"
    assert [row[0] for row in test_db.execute(
        "SELECT event_name FROM events "
        "WHERE event_name LIKE 'DecisionRequest%' ORDER BY created_at, id"
    ).fetchall()] == ["DecisionRequestCreated", "DecisionRequestResolved"]
