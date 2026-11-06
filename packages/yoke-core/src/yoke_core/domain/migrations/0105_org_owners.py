"""Promote each organization's earliest active human admin to owner."""

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
RETIRES_INVARIANTS = ("0062_one_org_role_per_person",)


def _candidates(conn):
    if not _table_exists(conn, "actor_org_roles"):
        return []
    return conn.execute(
        "SELECT ar.org_id, ar.actor_id FROM actor_org_roles ar "
        "JOIN roles r ON r.id=ar.role_id JOIN actors a ON a.id=ar.actor_id "
        "WHERE r.name='admin' AND a.kind='human' AND a.status='active' "
        "AND NOT EXISTS (SELECT 1 FROM actor_org_roles owners "
        "JOIN roles ro ON ro.id=owners.role_id JOIN actors ao ON ao.id=owners.actor_id "
        "WHERE owners.org_id=ar.org_id AND ro.name='owner' "
        "AND ao.kind='human' AND ao.status='active') "
        "ORDER BY ar.org_id, a.created_at, a.id"
    ).fetchall()


def apply(conn):
    p = "%s" if connection_is_postgres(conn) else "?"
    chosen = {}
    for org_id, actor_id in _candidates(conn):
        chosen.setdefault(int(org_id), int(actor_id))
    for org_id, actor_id in chosen.items():
        conn.execute(
            f"DELETE FROM actor_org_roles WHERE org_id={p} AND actor_id={p}",
            (org_id, actor_id),
        )
        conn.execute(
            "INSERT INTO actor_org_roles "
            "(actor_id,org_id,role_id,granted_at,granted_by_actor_id) "
            f"SELECT {p},{p},id,CURRENT_TIMESTAMP,{p} FROM roles WHERE name='owner'",
            (actor_id, org_id, actor_id),
        )


def invariants(conn):
    if _candidates(conn):
        raise AssertionError(
            "org_owner_missing: an org with an active human admin has no owner. "
            "Recovery: rehearse and apply the org owner migration."
        )
    if not _table_exists(conn, "actor_org_roles"):
        return
    invalid = conn.execute(
        "SELECT ar.actor_id FROM actor_org_roles ar JOIN roles r ON r.id=ar.role_id "
        "JOIN actors a ON a.id=ar.actor_id WHERE a.kind='human' "
        "GROUP BY ar.actor_id,ar.org_id HAVING COUNT(*) > 1 OR "
        "SUM(CASE WHEN r.name IN ('owner','admin','operator','viewer') THEN 1 ELSE 0 END)=0"
    ).fetchone()
    if invalid:
        raise AssertionError(
            "invalid_person_org_role: each person must hold one human role per org. "
            "Recovery: ask an owner to replace the person's org role."
        )
