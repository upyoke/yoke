"""approval_on_done enablement requires a live human project owner."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.item_posture_amend import amend_item_posture
from yoke_core.domain.item_posture_amend_guards import ItemPostureAmendError


def _dash(conn, *, item_id: int) -> int:
    row = insert_item(
        conn,
        id=item_id,
        workflow_id="dash",
        status="idea",
        workflow_posture=json.dumps({}),
    )
    return int(row["id"])


def _project_id(conn, item_id: int) -> int:
    return int(
        conn.execute(
            "SELECT project_id FROM items WHERE id = %s", (item_id,)
        ).fetchone()[0]
    )


def _ensure_human_owner(conn, project_id: int) -> None:
    seed_roles_and_permissions(conn)
    conn.execute(
        "INSERT INTO actors (id, kind, system_component, created_at) "
        "VALUES (9101, 'human', NULL, NOW()) ON CONFLICT DO NOTHING"
    )
    grant_actor_project_role(
        conn,
        actor_id=9101,
        project_id=project_id,
        role_name=ROLE_OWNER,
    )


def test_enabling_approval_on_done_accepts_a_human_project_owner() -> None:
    with test_database() as conn:
        item_id = _dash(conn, item_id=2820)
        project_id = _project_id(conn, item_id)
        _ensure_human_owner(conn, project_id)
        result = amend_item_posture(
            conn,
            item_id=item_id,
            key="approval_on_done",
            value=True,
            reason="operator selected owner approval at done",
        )
        assert result["changed"] is True
        assert result["after"]["approval_on_done"] is True


def test_enabling_approval_on_done_refuses_when_only_system_owners_exist() -> None:
    with test_database() as conn:
        item_id = _dash(conn, item_id=2821)
        project_id = _project_id(conn, item_id)
        conn.execute(
            "UPDATE actors SET kind = 'system' WHERE id IN ("
            "SELECT apr.actor_id FROM actor_project_roles apr "
            "JOIN roles r ON r.id = apr.role_id "
            "WHERE apr.project_id = %s AND r.name = 'owner')",
            (project_id,),
        )
        conn.commit()
        with pytest.raises(ItemPostureAmendError, match="human project owner"):
            amend_item_posture(
                conn,
                item_id=item_id,
                key="approval_on_done",
                value=True,
                reason="no human can answer this gate",
            )


def test_org_admin_alone_does_not_enable_owner_only_approval() -> None:
    with test_database() as conn:
        item_id = _dash(conn, item_id=2822)
        project_id = _project_id(conn, item_id)
        conn.execute(
            "DELETE FROM actor_project_roles WHERE project_id = %s "
            "AND role_id = (SELECT id FROM roles WHERE name = 'owner')",
            (project_id,),
        )
        conn.commit()
        with pytest.raises(ItemPostureAmendError, match="human project owner"):
            amend_item_posture(
                conn,
                item_id=item_id,
                key="approval_on_done",
                value=True,
                reason="org admin is not the owner-only roster",
            )
