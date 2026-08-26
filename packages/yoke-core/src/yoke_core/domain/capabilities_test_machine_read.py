"""Test-machine readiness facts used by the capability roster."""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
)
from yoke_contracts.item_ref import format_item_ref

from yoke_core.domain import db_backend
from yoke_core.domain.machine_qa_capability import lease_key
from yoke_core.domain.machine_qa_host_registrar import host_registrations
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.qa_method_capabilities import capability_kinds
from yoke_core.domain.work_claim_targets import scope_int_sql


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
    host_keys = {
        registration.project_id: lease_key(registration.resource_name)
        for registration in host_registrations(conn)
        if registration.project_id in requested
    }
    active_sessions: dict[int, str] = {}
    if host_keys and _table_exists(conn, "coordination_leases"):
        # The host lease lives under whichever project registered the machine,
        # so a shared host is busy for every project that names it.
        keys = sorted(set(host_keys.values()))
        key_markers = ", ".join([marker] * len(keys))
        holders = {
            str(row["lease_key"]): str(row["session_id"])
            for row in conn.execute(
                "SELECT lease_key,session_id FROM coordination_leases "
                f"WHERE lease_key IN ({key_markers}) AND released_at IS NULL",
                tuple(keys),
            ).fetchall()
        }
        active_sessions = {
            project_id: holders[key]
            for project_id, key in host_keys.items()
            if key in holders
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
