"""Test-machine readiness facts used by the capability roster."""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
)
from yoke_contracts.item_ref import format_item_ref

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists


def read_test_machine_facts(
    conn: Any,
    project_ids: list[int],
) -> tuple[dict[int, str], dict[int, str | None], int]:
    """Return verification states, active-lease item refs, and method count."""
    if not project_ids:
        return {}, {}, 0
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join([marker] * len(project_ids))
    verification = {}
    if _table_exists(conn, "test_machine_verifications"):
        verification = {
            int(row["project_id"]): str(row["status"])
            for row in conn.execute(
                "SELECT project_id,status FROM test_machine_verifications "
                f"WHERE project_id IN ({placeholders})",
                tuple(project_ids),
            ).fetchall()
        }
    active_sessions: dict[int, str] = {}
    if _table_exists(conn, "coordination_leases"):
        active_sessions = {
            int(row["project_id"]): str(row["session_id"])
            for row in conn.execute(
                "SELECT project_id,session_id FROM coordination_leases "
                f"WHERE project_id IN ({placeholders}) "
                "AND lease_key LIKE 'QA_HOST:%%' AND released_at IS NULL",
                tuple(project_ids),
            ).fetchall()
        }
    active_items: dict[int, str | None] = {
        project_id: None for project_id in active_sessions
    }
    required_columns = {
        "work_claims": (
            "id", "session_id", "target_kind", "item_id",
            "claimed_at", "released_at",
        ),
        "items": ("id", "project_id", "project_sequence"),
        "projects": ("id", "slug", "public_item_prefix"),
    }
    if active_sessions and all(
        _table_exists(conn, table)
        and all(_column_exists(conn, table, column) for column in columns)
        for table, columns in required_columns.items()
    ):
        sessions = sorted(set(active_sessions.values()))
        session_markers = ", ".join([marker] * len(sessions))
        refs_by_session: dict[str, str] = {}
        rows = conn.execute(
            "SELECT wc.session_id,wc.item_id,i.project_sequence,"
            "p.slug,p.public_item_prefix "
            "FROM work_claims wc "
            "JOIN items i ON i.id=wc.item_id "
            "JOIN projects p ON p.id=i.project_id "
            f"WHERE wc.session_id IN ({session_markers}) "
            "AND wc.target_kind='item' AND wc.released_at IS NULL "
            "ORDER BY wc.claimed_at DESC,wc.id DESC",
            tuple(sessions),
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            session_id = str(row["session_id"])
            refs_by_session.setdefault(
                session_id,
                format_item_ref(
                    row["slug"],
                    row["public_item_prefix"],
                    row["project_sequence"],
                    item_id=int(row["item_id"]),
                ),
            )
        active_items = {
            project_id: refs_by_session.get(session_id)
            for project_id, session_id in active_sessions.items()
        }
    count_row = None
    if _table_exists(conn, "qa_methods"):
        count_row = conn.execute(
            "SELECT COUNT(*) FROM qa_methods "
            f"WHERE required_capability_kind={marker}",
            (TEST_MACHINE_CAPABILITY,),
        ).fetchone()
    return verification, active_items, int(count_row[0] if count_row else 0)


__all__ = ["read_test_machine_facts"]
