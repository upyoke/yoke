"""Every person converges to one org role; unusable pending invites are revoked."""

import importlib
import sqlite3

import pytest

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0061_one_org_role_per_person"
)

ROLES = ["admin", "operator", "viewer", "migration_verification_ci", "deployment_ci"]


def database():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE roles (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE actors (id INTEGER PRIMARY KEY, kind TEXT);
        CREATE TABLE actor_org_roles (actor_id INTEGER, org_id INTEGER, role_id INTEGER);
        CREATE TABLE actor_invites (id INTEGER PRIMARY KEY, role_id INTEGER, status TEXT);
        """
    )
    for index, name in enumerate(ROLES, start=1):
        conn.execute("INSERT INTO roles VALUES (?, ?)", (index, name))
    return conn


def grant(conn, actor_id, *names, kind="human", org_id=1):
    conn.execute("INSERT OR IGNORE INTO actors VALUES (?, ?)", (actor_id, kind))
    for name in names:
        conn.execute(
            "INSERT INTO actor_org_roles VALUES (?, ?, ?)",
            (actor_id, org_id, ROLES.index(name) + 1),
        )


def roles_of(conn, actor_id):
    rows = conn.execute(
        "SELECT r.name FROM actor_org_roles a JOIN roles r ON r.id = a.role_id "
        "WHERE a.actor_id = ? ORDER BY r.name",
        (actor_id,),
    ).fetchall()
    return [row[0] for row in rows]


def test_people_keep_their_strongest_role_and_machines_are_untouched():
    conn = database()
    grant(conn, 1, "operator", "admin")
    grant(conn, 2, "viewer", "operator", "migration_verification_ci")
    grant(conn, 3, "migration_verification_ci")
    grant(conn, 4, "viewer")
    grant(conn, 5, "admin", "migration_verification_ci", kind="system")
    conn.executemany(
        "INSERT INTO actor_invites VALUES (?, ?, ?)",
        [
            (1, ROLES.index("deployment_ci") + 1, "pending"),
            (2, ROLES.index("operator") + 1, "pending"),
            (3, ROLES.index("deployment_ci") + 1, "accepted"),
        ],
    )

    with pytest.raises(AssertionError, match="person_org_roles_not_collapsed"):
        MIGRATION.invariants(conn)
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)

    assert roles_of(conn, 1) == ["admin"]
    assert roles_of(conn, 2) == ["operator"]
    assert roles_of(conn, 3) == []
    assert roles_of(conn, 4) == ["viewer"]
    assert roles_of(conn, 5) == ["admin", "migration_verification_ci"]
    statuses = dict(conn.execute("SELECT id, status FROM actor_invites").fetchall())
    assert statuses == {1: "revoked", 2: "pending", 3: "accepted"}
    before = conn.total_changes
    MIGRATION.apply(conn)
    assert conn.total_changes == before
