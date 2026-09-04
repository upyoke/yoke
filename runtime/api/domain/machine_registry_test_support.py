"""SQLite fixture for machine-registry, access, and relay-guard tests."""

from __future__ import annotations

import sqlite3

from yoke_core.domain.machine_registry_schema import ensure_machine_registry_schema


NOW = "2026-09-03T12:00:00Z"
MACHINE_ID = "11111111-1111-4111-8111-111111111111"
OTHER_MACHINE_ID = "22222222-2222-4222-8222-222222222222"


def registry_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE actors (id INTEGER PRIMARY KEY);
        CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT NOT NULL, org_id INTEGER);
        CREATE TABLE roles (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE actor_project_roles (
            actor_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL
        );
        CREATE TABLE actor_org_roles (
            actor_id INTEGER NOT NULL,
            org_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL
        );
        INSERT INTO actors (id) VALUES (1), (2), (3);
        INSERT INTO projects (id, slug, org_id) VALUES (10, 'registry-project', 1);
        INSERT INTO roles (id, name) VALUES (1, 'maintainer');
        """
    )
    ensure_machine_registry_schema(conn)
    return conn


def grant_project_role(
    conn: sqlite3.Connection,
    *,
    actor_id: int,
    project_id: int = 10,
    role_id: int = 1,
) -> None:
    conn.execute(
        "INSERT INTO actor_project_roles (actor_id, project_id, role_id) "
        "VALUES (?, ?, ?)",
        (actor_id, project_id, role_id),
    )
    conn.commit()


__all__ = [
    "MACHINE_ID",
    "NOW",
    "OTHER_MACHINE_ID",
    "grant_project_role",
    "registry_connection",
]
