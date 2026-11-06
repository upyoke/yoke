"""Seed starting project authority for tests without invoking grant authorization.

Tests of role-grant authorization call the production writer directly. Other
fixtures declare their initial grants here, before exercising their own behavior.
"""

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.actor_permissions import role_id_by_name
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain import db_backend


def seed_project_role(
    conn,
    *,
    actor_id,
    project_id,
    role_name,
    granted_by_actor_id=None,
    commit=True,
):
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id,project_id,role_id,granted_at,granted_by_actor_id) "
        f"VALUES ({p},{p},{p},{p},{p}) "
        "ON CONFLICT(actor_id,project_id,role_id) DO NOTHING",
        (
            actor_id,
            project_id,
            role_id_by_name(conn, role_name),
            instant_parameter(conn, utc_now()),
            granted_by_actor_id,
        ),
    )
    if commit:
        conn.commit()


def seed_org_role(
    conn,
    *,
    actor_id,
    org_id,
    role_name,
    granted_by_actor_id=None,
    commit=True,
):
    """Declare a fixture's initial org role; people have exactly one."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    person = conn.execute(
        f"SELECT kind FROM actors WHERE id={p}", (actor_id,)
    ).fetchone()
    if person and person[0] == "human":
        conn.execute(
            f"DELETE FROM actor_org_roles WHERE actor_id={p} AND org_id={p}",
            (actor_id, org_id),
        )
    conn.execute(
        "INSERT INTO actor_org_roles "
        "(actor_id,org_id,role_id,granted_at,granted_by_actor_id) "
        f"VALUES ({p},{p},{p},{p},{p}) "
        "ON CONFLICT(actor_id,org_id,role_id) DO NOTHING",
        (
            actor_id,
            org_id,
            role_id_by_name(conn, role_name),
            instant_parameter(conn, utc_now()),
            granted_by_actor_id,
        ),
    )
    if commit:
        conn.commit()


def seed_human_reviewer(conn, project_id, *, commit=True):
    """Staff a test gate with a real active person before creating its request."""
    from yoke_core.domain.actors import seed_human_actor

    actor_id = seed_human_actor(conn, "Gate reviewer", commit=False)
    seed_project_role(
        conn, actor_id=actor_id, project_id=project_id, role_name="owner", commit=commit
    )
    return actor_id


def seed_service_actor(conn):
    from uuid import uuid4
    from yoke_core.domain.actors import seed_system_actor

    return seed_system_actor(conn, "test-service-" + str(uuid4()))
