"""approval_on_done enablement accepts effective human owner or admin authority."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.actor_permissions import (
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
    conn.execute(
        "INSERT INTO actor_project_roles (actor_id,project_id,role_id,granted_at) "
        "SELECT 9101,%s,id,NOW() FROM roles WHERE name='owner'",
        (project_id,),
    )
    conn.commit()


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
        with pytest.raises(ItemPostureAmendError, match="empty_audience_members"):
            amend_item_posture(
                conn,
                item_id=item_id,
                key="approval_on_done",
                value=True,
                reason="no human can answer this gate",
            )


def test_org_admin_alone_enables_owner_approval() -> None:
    with test_database() as conn:
        item_id = _dash(conn, item_id=2822)
        project_id = _project_id(conn, item_id)
        seed_roles_and_permissions(conn)
        conn.execute(
            "DELETE FROM actor_project_roles WHERE project_id=%s", (project_id,)
        )
        conn.execute(
            "INSERT INTO actors (id,kind,created_at) VALUES (9101,'human',NOW())"
        )
        conn.execute(
            "INSERT INTO actor_org_roles (actor_id,org_id,role_id,granted_at) "
            "SELECT 9101,p.org_id,r.id,NOW() FROM projects p CROSS JOIN roles r "
            "WHERE p.id=%s AND r.name='admin'",
            (project_id,),
        )
        conn.commit()
        result = amend_item_posture(
            conn,
            item_id=item_id,
            key="approval_on_done",
            value=True,
            reason="org admin satisfies the effective owner rank",
        )
        assert result["after"]["approval_on_done"] is True
