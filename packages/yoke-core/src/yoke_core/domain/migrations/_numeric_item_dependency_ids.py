"""Frozen helpers for the numeric item-dependency id cutover."""

from __future__ import annotations

import sys
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


_NEXT_TABLE = "item_dependencies_next"

_NEXT_DDL = f"""
CREATE TABLE {_NEXT_TABLE} (
    id INTEGER PRIMARY KEY,
    dependent_item_id INTEGER NOT NULL REFERENCES items(id),
    blocking_item_id INTEGER NOT NULL REFERENCES items(id),
    gate_point TEXT NOT NULL DEFAULT 'activation',
    satisfaction TEXT NOT NULL DEFAULT 'status:done',
    source TEXT NOT NULL,
    session_id INTEGER,
    rationale TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{{}}',
    created_at TEXT NOT NULL,
    UNIQUE(dependent_item_id, blocking_item_id, gate_point)
);
"""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def registry_is_numeric(conn: Any) -> bool:
    if not _table_exists(conn, "item_dependencies"):
        return True
    return _column_exists(conn, "item_dependencies", "dependent_item_id") and not (
        _column_exists(conn, "item_dependencies", "dependent_item")
    )


def _row_map(cursor: Any, raw: Any) -> dict[str, Any]:
    columns = [str(column[0]) for column in cursor.description]
    if hasattr(raw, "keys"):
        return {name: raw[name] for name in columns}
    return dict(zip(columns, raw, strict=True))


def _resolve_stored(conn: Any, value: Any) -> Optional[int]:
    """Public-ref first, then numeric tail as ``items.id``."""
    text = str(value).strip()
    placeholder = _p(conn)
    if (
        _table_exists(conn, "items")
        and _table_exists(conn, "projects")
        and _column_exists(conn, "projects", "public_item_prefix")
        and _column_exists(conn, "items", "project_sequence")
    ):
        row = conn.execute(
            "SELECT ri.id FROM items ri JOIN projects rp ON rp.id = ri.project_id "
            "WHERE UPPER(rp.public_item_prefix) || '-' "
            f"|| CAST(ri.project_sequence AS TEXT) = UPPER({placeholder})",
            (text,),
        ).fetchone()
        if row is not None:
            return int(row["id"] if hasattr(row, "keys") else row[0])
    tail = text.rsplit("-", 1)[-1]
    if not tail.isdigit() or not _table_exists(conn, "items"):
        return None
    item_id = int(tail.lstrip("0") or "0")
    row = conn.execute(
        f"SELECT id FROM items WHERE id = {placeholder}",
        (item_id,),
    ).fetchone()
    if row is None:
        return None
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _report_orphan(row: dict[str, Any]) -> None:
    print(
        "dropped orphan item_dependencies "
        f"id={row.get('id')} dependent_item={row.get('dependent_item')!r} "
        f"blocking_item={row.get('blocking_item')!r} "
        f"gate_point={row.get('gate_point')!r} source={row.get('source')!r}",
        file=sys.stderr,
    )


def _copy_resolved_rows(conn: Any) -> None:
    cursor = conn.execute(
        "SELECT id, dependent_item, blocking_item, gate_point, satisfaction, "
        "source, session_id, rationale, evidence_json, created_at "
        "FROM item_dependencies"
    )
    placeholder = _p(conn)
    slots = ", ".join(placeholder for _ in range(10))
    dropped = 0
    for raw in cursor.fetchall():
        row = _row_map(cursor, raw)
        dependent_id = _resolve_stored(conn, row["dependent_item"])
        blocking_id = _resolve_stored(conn, row["blocking_item"])
        if dependent_id is None or blocking_id is None:
            _report_orphan(row)
            dropped += 1
            continue
        conn.execute(
            f"INSERT INTO {_NEXT_TABLE} ("
            "id, dependent_item_id, blocking_item_id, gate_point, satisfaction, "
            "source, session_id, rationale, evidence_json, created_at"
            f") VALUES ({slots})",
            (
                row["id"],
                dependent_id,
                blocking_id,
                row["gate_point"],
                row["satisfaction"],
                row["source"],
                row["session_id"],
                row["rationale"] or "",
                row["evidence_json"] or "{}",
                row["created_at"],
            ),
        )
    if dropped:
        print(
            f"dropped {dropped} orphan item_dependencies row(s) "
            "that resolved under neither public-ref nor numeric-tail reading",
            file=sys.stderr,
        )


def _replace_table(conn: Any) -> None:
    conn.execute("DROP TABLE item_dependencies")
    conn.execute(f"ALTER TABLE {_NEXT_TABLE} RENAME TO item_dependencies")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_id_dependent "
        "ON item_dependencies(dependent_item_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_id_blocking "
        "ON item_dependencies(blocking_item_id)"
    )
    if not db_backend.connection_is_postgres(conn):
        return
    sequence = conn.execute(
        "SELECT pg_get_serial_sequence('item_dependencies', 'id')"
    ).fetchone()
    sequence_name = sequence[0] if sequence else None
    if not sequence_name:
        return
    conn.execute(
        f"SELECT setval('{sequence_name}', "
        "COALESCE((SELECT MAX(id) FROM item_dependencies), 1))"
    )


def rebuild_registry(conn: Any) -> None:
    if registry_is_numeric(conn) or not _table_exists(conn, "item_dependencies"):
        return
    if _table_exists(conn, _NEXT_TABLE):
        conn.execute(f"DROP TABLE {_NEXT_TABLE}")
    execute_schema_script(conn, _NEXT_DDL)
    _copy_resolved_rows(conn)
    _replace_table(conn)


__all__ = ["rebuild_registry", "registry_is_numeric"]
