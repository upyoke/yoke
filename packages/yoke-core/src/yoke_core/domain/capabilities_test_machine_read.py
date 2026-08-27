"""Test-machine readiness facts used by the capability roster."""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
)
from yoke_contracts.item_ref import format_item_ref

from yoke_core.domain import db_backend
from yoke_core.domain.machine_qa_capability import host_claim_target
from yoke_core.domain.machine_qa_host_registrar import host_registrations
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.qa_method_capabilities import capability_kinds
from yoke_core.domain.work_claim_target_sql import (
    scope_int_sql,
    scope_text_sql,
)
from yoke_core.domain.work_claim_targets import TARGET_KIND_QA_ADMISSION


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
    requested = set(project_ids)
    host_machines = {
        registration.project_id: host_claim_target(
            registration.resource_name
        ).machine_id
        for registration in host_registrations(conn)
        if registration.project_id in requested
    }
    active_sessions: dict[int, str] = {}
    if host_machines and _table_exists(conn, "work_claims"):
        # One physical host is one claim, so a shared machine reads busy
        # for every project that names it.
        machines = sorted(set(host_machines.values()))
        machine_markers = ", ".join([marker] * len(machines))
        machine_expr = scope_text_sql(conn, "scope", "machine_id")
        holders = {
            str(row[0]): str(row[1])
            for row in conn.execute(
                f"SELECT {machine_expr}, session_id FROM work_claims "
                f"WHERE target_kind='{TARGET_KIND_QA_ADMISSION}' "
                f"AND {machine_expr} IN ({machine_markers}) "
                "AND released_at IS NULL",
                tuple(machines),
            ).fetchall()
        }
        active_sessions = {
            project_id: holders[machine]
            for project_id, machine in host_machines.items()
            if machine in holders
        }
    active_items: dict[int, str | None] = {
        project_id: None for project_id in active_sessions
    }
    required_columns = {
        "work_claims": (
            "id",
            "session_id",
            "target_kind",
            "scope",
            "claimed_at",
            "released_at",
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
        item_id_scope = scope_int_sql(conn, "wc.scope", "item_id")
        rows = conn.execute(
            f"SELECT wc.session_id,{item_id_scope} AS item_id,i.project_sequence,"
            "p.slug,p.public_item_prefix "
            "FROM work_claims wc "
            f"JOIN items i ON i.id={item_id_scope} "
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
    method_count = 0
    if _table_exists(conn, "qa_methods"):
        methods = conn.execute(
            "SELECT id,required_capability_kinds FROM qa_methods"
        ).fetchall()
        method_count = sum(
            TEST_MACHINE_CAPABILITY
            in capability_kinds(
                row["required_capability_kinds"],
                subject=f"method {row['id']!r}",
            )
            for row in methods
        )
    return verification, active_items, method_count


__all__ = ["read_test_machine_facts"]
