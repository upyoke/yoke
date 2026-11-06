"""Org owner migration is scoped, ordered, idempotent and floor-protected."""

from importlib import import_module

from runtime.api.domain.decision_request_test_support import decision_request_connection

migration = import_module("yoke_core.domain.migrations.0105_org_owners")


def test_earliest_active_human_admin_becomes_owner_and_others_are_unchanged():
    with decision_request_connection() as conn:
        conn.execute(
            "ALTER TABLE actor_org_roles ADD COLUMN granted_by_actor_id INTEGER"
        )
        conn.execute("INSERT INTO actor_org_roles VALUES (2, 1, 3, 'now', NULL)")
        conn.execute("INSERT INTO actor_org_roles VALUES (1, 1, 3, 'now', NULL)")
        conn.execute("UPDATE actors SET status='disabled' WHERE id=1")
        before = [
            tuple(row) for row in conn.execute("SELECT * FROM actor_project_roles")
        ]
        migration.apply(conn)
        migration.invariants(conn)
        roles = [
            tuple(row)
            for row in conn.execute(
                "SELECT ar.actor_id,r.name FROM actor_org_roles ar JOIN roles r ON r.id=ar.role_id "
                "ORDER BY ar.actor_id"
            )
        ]
        assert roles == [
            (1, "admin"),
            (2, "owner"),
            (5, "admin"),
            (6, "hosted_service"),
        ]
        assert [
            tuple(row) for row in conn.execute("SELECT * FROM actor_project_roles")
        ] == before
        migration.apply(conn)
        migration.invariants(conn)
        assert [
            tuple(row)
            for row in conn.execute(
                "SELECT ar.actor_id,r.name FROM actor_org_roles ar JOIN roles r ON r.id=ar.role_id "
                "ORDER BY ar.actor_id"
            )
        ] == roles
        assert migration.MINIMUM_SERVING_VERSION == "next-release"
        assert migration.RETIRES_INVARIANTS == ("0062_one_org_role_per_person",)
