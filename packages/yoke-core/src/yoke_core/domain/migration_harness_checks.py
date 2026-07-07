"""Verification helpers shared by the migration harness and CLI."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.migration_apply_contract import (
    STATE_PLANNED,
    STATE_REHEARSED,
    _now,
)
from yoke_core.domain.schema_common import _get_tables


def _quote_identifier(raw: str) -> str:
    return '"' + raw.replace('"', '""') + '"'


def _operational_error_types(conn) -> tuple:
    return db_backend.database_error_types(conn)


def _count_all_tables(conn: Any) -> Dict[str, int]:
    """Return row counts for every user table in the DB."""
    counts: Dict[str, int] = {}
    for name in _get_tables(conn):
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(str(name))}"
            ).fetchone()
            counts[name] = row[0] if row else 0
        except _operational_error_types(conn):
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            counts[name] = -1
    return counts


def _fk_violation_count(conn: Any) -> int:
    """Return count of FK violations (0 = clean)."""
    if db_backend.connection_is_postgres(conn):
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM pg_constraint con "
                "JOIN pg_namespace ns ON ns.oid = con.connamespace "
                "WHERE ns.nspname = current_schema() "
                "AND con.contype = 'f' AND NOT con.convalidated"
            ).fetchone()
            return int(row[0]) if row else 0
        except db_backend.operational_error_types(conn):
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            return -1
    try:
        rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        return len(rows)
    except db_backend.database_error_types(conn):
        return -1


def pg_insert_migration_audit_row(
    audit_conn,
    *,
    name: str,
    model_name: str,
    project_id: int,
    session_id: Optional[str],
    test_copy_path: Optional[str],
    tables: List[str],
    description: Optional[str] = None,
) -> int:
    from yoke_core.domain.migration_apply_audit import DESCRIPTION_BASE

    cur = audit_conn.execute(
        "INSERT INTO migration_audit "
        "(migration_name, description, tables_declared, expected_deltas, "
        "pre_row_counts, pre_fk_violations, backup_path, started_at, "
        "state, model_name, project_id, session_id, test_copy_path) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "RETURNING id",
        (
            name,
            description or DESCRIPTION_BASE,
            json.dumps(tables),
            json.dumps({t: 0 for t in tables}),
            json.dumps({}),
            0,
            "",
            _now(),
            STATE_PLANNED,
            model_name,
            project_id,
            session_id,
            test_copy_path,
        ),
    )
    audit_id = int(cur.fetchone()[0])
    audit_conn.commit()
    return audit_id


def pg_update_migration_audit_state(
    audit_conn,
    audit_id: int,
    state: str,
    *,
    extra: Optional[Mapping[str, Any]] = None,
) -> None:
    sets = ["state = %s"]
    values: List[Any] = [state]
    for column, value in (extra or {}).items():
        sets.append(f"{_quote_identifier(str(column))} = %s")
        values.append(value)
    values.append(audit_id)
    audit_conn.execute(
        f"UPDATE migration_audit SET {', '.join(sets)} WHERE id = %s",
        tuple(values),
    )
    audit_conn.commit()


def pg_latest_rehearsed_migration_audit_row(
    audit_conn, identifier: str, model_name: str, *, project_id: int,
) -> Optional[Dict[str, Any]]:
    try:
        cur = audit_conn.execute(
            "SELECT id, state, source_fingerprint, rehearsed_at, "
            "baseline_verify_result, author_verify_result, test_copy_path, "
            "description FROM migration_audit WHERE migration_name = %s "
            "AND project_id = %s "
            "AND COALESCE(model_name, %s) = %s "
            "AND state = %s ORDER BY id DESC LIMIT 1",
            (identifier, project_id, model_name, model_name, STATE_REHEARSED),
        )
        row = cur.fetchone()
    except db_backend.operational_error_types(audit_conn):
        _rollback_after_error(audit_conn)
        return None
    if row is None:
        return None
    return _row_to_dict(cur, row)


def pg_set_migration_audit_provenance(
    audit_conn,
    audit_id: int,
    provenance: Mapping[str, Optional[str]],
) -> None:
    from yoke_core.domain.migration_apply_audit import PROVENANCE_COLUMNS

    sets: List[str] = []
    values: List[Any] = []
    for column in PROVENANCE_COLUMNS:
        if column not in provenance:
            continue
        sets.append(f"{_quote_identifier(column)} = %s")
        values.append(provenance[column])
    if not sets:
        return
    values.append(audit_id)
    try:
        audit_conn.execute(
            f"UPDATE migration_audit SET {', '.join(sets)} WHERE id = %s",
            tuple(values),
        )
        audit_conn.commit()
    except db_backend.operational_error_types(audit_conn):
        _rollback_after_error(audit_conn)


def _rollback_after_error(conn) -> None:
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001
        return


def _row_to_dict(cur, row) -> Dict[str, Any]:
    if hasattr(row, "keys"):
        return dict(row)
    columns = [getattr(desc, "name", desc[0]) for desc in (cur.description or [])]
    return dict(zip(columns, row))
