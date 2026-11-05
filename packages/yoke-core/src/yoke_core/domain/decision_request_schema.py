"""Idempotent storage hook for decision requests."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.decision_request_contract import DECISION_REQUEST_KINDS
from yoke_core.domain.audience_schema import create_audience_tables
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
    create_audience_tables(conn, commit=False)
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
            audience_id INTEGER REFERENCES audiences(id),
            approval_mode TEXT NOT NULL DEFAULT 'any'
                CHECK(approval_mode IN ('any', 'all')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'resolved', 'withdrawn')),
            resolution_action TEXT,
            resolution_actor_id INTEGER REFERENCES actors(id),
            resolution_note TEXT,
            resolved_at TIMESTAMPTZ,
            withdrawal_reason TEXT,
            withdrawn_at TIMESTAMPTZ,
            consumed_at TIMESTAMPTZ,
            consumed_from_stage TEXT,
            consumed_to_stage TEXT,
            consumed_workflow_version_id INTEGER,
            created_at TIMESTAMPTZ NOT NULL,
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

        CREATE TABLE IF NOT EXISTS decision_request_decisions (
            id INTEGER PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES decision_requests(id)
                ON DELETE CASCADE,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            action TEXT NOT NULL,
            note TEXT,
            decided_at TIMESTAMPTZ NOT NULL,
            -- Which session answered, beside which actor did. On a machine
            -- whose surfaces share one operator credential the actor is
            -- the same for every one of them, so the session is the only
            -- thing an audit can tell them apart by.
            decided_session_id TEXT,
            UNIQUE (request_id, actor_id)
        );
        CREATE INDEX IF NOT EXISTS idx_decision_request_decisions_request
            ON decision_request_decisions(request_id, decided_at, id);
    """,
    )
    _add_column_if_not_exists(
        conn, "decision_requests", "audience_id", "INTEGER REFERENCES audiences(id)"
    )
    _add_column_if_not_exists(
        conn,
        "decision_request_decisions",
        "decided_session_id",
        "TEXT",
    )
    _add_column_if_not_exists(
        conn,
        "decision_requests",
        "approval_mode",
        "TEXT NOT NULL DEFAULT 'any' CHECK(approval_mode IN ('any', 'all'))",
    )
    _add_column_if_not_exists(
        conn,
        "decision_requests",
        "consumed_at",
        "TIMESTAMPTZ",
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
    _add_column_if_not_exists(
        conn, "decision_requests", "requesting_session_id", "TEXT"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_requests_requesting_session "
        "ON decision_requests(requesting_session_id, status, created_at)"
    )
    if commit:
        conn.commit()


__all__ = ["create_decision_request_tables"]
