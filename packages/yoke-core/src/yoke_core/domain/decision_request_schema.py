"""Idempotent storage hook for decision requests."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.decision_request_contract import (
    DECISION_EVENT_ROWS,
    DECISION_REQUEST_KINDS,
)
from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def create_decision_request_tables(
    conn: Any,
    *,
    commit: bool = True,
) -> None:
    """Create the Inbox substrate, committing unless the caller owns the transaction."""
    request_kinds = _sql_values(DECISION_REQUEST_KINDS)
    execute_schema_script(
        conn,
        f"""
        CREATE TABLE IF NOT EXISTS decision_requests (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN ({request_kinds})),
            subject_type TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            subject_context TEXT NOT NULL DEFAULT '{{}}',
            project_id INTEGER REFERENCES projects(id),
            org_id INTEGER REFERENCES organizations(id),
            originator_actor_id INTEGER REFERENCES actors(id),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'resolved', 'withdrawn')),
            resolution_action TEXT,
            resolution_actor_id INTEGER REFERENCES actors(id),
            resolution_note TEXT,
            resolved_at TEXT,
            withdrawal_reason TEXT,
            withdrawn_at TEXT,
            consumed_at TEXT,
            consumed_from_stage TEXT,
            consumed_to_stage TEXT,
            consumed_workflow_version_id INTEGER,
            created_at TEXT NOT NULL,
            CHECK (
                (project_id IS NOT NULL AND org_id IS NULL)
                OR (project_id IS NULL AND org_id IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_decision_requests_open_subject
            ON decision_requests(kind, subject_type, subject_key)
            WHERE status = 'pending';
        CREATE INDEX IF NOT EXISTS idx_decision_requests_project_status
            ON decision_requests(project_id, status, created_at);
        CREATE INDEX IF NOT EXISTS idx_decision_requests_org_status
            ON decision_requests(org_id, status, created_at);

        CREATE TABLE IF NOT EXISTS decision_request_role_authorities (
            request_id INTEGER NOT NULL REFERENCES decision_requests(id)
                ON DELETE CASCADE,
            scope_kind TEXT NOT NULL CHECK(scope_kind IN ('project', 'org')),
            scope_id INTEGER NOT NULL,
            role_name TEXT NOT NULL,
            PRIMARY KEY (request_id, scope_kind, scope_id, role_name)
        );
        CREATE INDEX IF NOT EXISTS idx_decision_request_roles_scope
            ON decision_request_role_authorities(
                scope_kind, scope_id, role_name, request_id
            );

        CREATE TABLE IF NOT EXISTS decision_request_actor_authorities (
            request_id INTEGER NOT NULL REFERENCES decision_requests(id)
                ON DELETE CASCADE,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            PRIMARY KEY (request_id, actor_id)
        );
        CREATE INDEX IF NOT EXISTS idx_decision_request_actors_actor
            ON decision_request_actor_authorities(actor_id, request_id);
    """,
    )
    _add_column_if_not_exists(
        conn,
        "decision_requests",
        "consumed_at",
        "TEXT",
    )
    _add_column_if_not_exists(
        conn,
        "decision_requests",
        "consumed_from_stage",
        "TEXT",
    )
    _add_column_if_not_exists(
        conn,
        "decision_requests",
        "consumed_to_stage",
        "TEXT",
    )
    _add_column_if_not_exists(
        conn,
        "decision_requests",
        "consumed_workflow_version_id",
        "INTEGER",
    )
    seed_decision_request_events(conn)
    if commit:
        conn.commit()


def seed_decision_request_events(conn: Any) -> None:
    """Converge the registered event names emitted by the substrate."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    for name, kind, event_type, description in DECISION_EVENT_ROWS:
        conn.execute(
            "INSERT INTO event_registry "
            "(event_name, event_kind, event_type, owner_service, description, "
            "severity_default, status) "
            f"VALUES ({p}, {p}, {p}, 'engine', {p}, 'INFO', 'active') "
            "ON CONFLICT(event_name) DO UPDATE SET "
            "event_kind=EXCLUDED.event_kind, event_type=EXCLUDED.event_type, "
            "owner_service=EXCLUDED.owner_service, "
            "description=EXCLUDED.description, "
            "severity_default=EXCLUDED.severity_default, status='active'",
            (name, kind, event_type, description),
        )


__all__ = ["create_decision_request_tables", "seed_decision_request_events"]
