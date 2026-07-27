"""Shared database fixture support for decision-request domain tests."""

from __future__ import annotations

from contextlib import contextmanager
import sqlite3

from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.events_schema import ensure_event_schema


@contextmanager
def decision_request_connection():
    value = sqlite3.connect(":memory:")
    value.row_factory = sqlite3.Row
    value.execute("PRAGMA foreign_keys = ON")
    value.executescript("""
        CREATE TABLE actors (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            system_component TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE actor_labels (
            id INTEGER PRIMARY KEY,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            surface TEXT NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE organizations (
            id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT, created_at TEXT
        );
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT,
            public_item_prefix TEXT DEFAULT 'YOK',
            org_id INTEGER REFERENCES organizations(id), created_at TEXT
        );
        CREATE TABLE roles (
            id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE actor_project_roles (
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            project_id INTEGER NOT NULL REFERENCES projects(id),
            role_id INTEGER NOT NULL REFERENCES roles(id),
            granted_at TEXT NOT NULL,
            PRIMARY KEY(actor_id, project_id, role_id)
        );
        CREATE TABLE actor_org_roles (
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            org_id INTEGER NOT NULL REFERENCES organizations(id),
            role_id INTEGER NOT NULL REFERENCES roles(id),
            granted_at TEXT NOT NULL,
            PRIMARY KEY(actor_id, org_id, role_id)
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            workflow_version_id INTEGER NOT NULL
        );
    """)
    ensure_event_schema(value)
    create_decision_request_tables(value)
    value.execute(
        "INSERT INTO organizations VALUES (1, 'default', 'Default', 'now')"
    )
    value.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, org_id, created_at) "
        "VALUES (10, 'yoke', 'Yoke', 'YOK', 1, 'now')"
    )
    for actor_id in range(1, 6):
        value.execute(
            "INSERT INTO actors VALUES (?, 'human', NULL, 'now')", (actor_id,)
        )
    for role_id, name in enumerate(("owner", "operator", "admin", "viewer"), 1):
        value.execute(
            "INSERT INTO roles VALUES (?, ?, '', 'now')", (role_id, name)
        )
    value.execute(
        "INSERT INTO actor_project_roles VALUES (2, 10, 1, 'now')"
    )
    value.execute(
        "INSERT INTO actor_project_roles VALUES (4, 10, 4, 'now')"
    )
    value.execute("INSERT INTO actor_org_roles VALUES (5, 1, 3, 'now')")
    value.commit()
    try:
        yield value
    finally:
        value.close()
