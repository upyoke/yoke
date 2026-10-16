"""Schema hints appended to a failed ``db.read.run`` query.

Names the live columns and packet notes of the tables a failed diagnostic
query referenced, so the caller can correct a guessed column or table.
"""

from __future__ import annotations

import re
from typing import Any

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.db_read_column_hints import column_hint, table_notes
from yoke_core.domain.schema_api_context_tables import CANONICAL_TABLES


_TABLE_REF_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)",
    re.IGNORECASE,
)
_NO_SUCH_TABLE_RE = re.compile(
    r"(?:no such table|relation .* does not exist):?\s+\"?([A-Za-z_][\w.]*)\"?",
    re.IGNORECASE,
)


def schema_hint_for_error(sql: str, exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if not any(
        token in lowered
        for token in (
            "no such column",
            "undefinedcolumn",
            "does not exist",
            "no such table",
            "undefinedtable",
        )
    ):
        return ""
    tables = _tables_for_error(sql, message)
    parts: list[str] = []
    for table in tables[:3]:
        columns = _live_columns_for_table(table)
        canonical = CANONICAL_TABLES.get(table)
        if columns:
            parts.append(
                f"Live columns for {table}: "
                + ", ".join(column_hint(table, name, dtype) for name, dtype in columns)
            )
        if canonical:
            notes = _compact_text(
                table_notes(table, columns, str(canonical.get("notes") or ""))
            )
            if notes:
                parts.append(f"Packet note for {table}: {notes}")
    if not parts:
        return ""
    return "Schema hint from db.read.run:\n" + "\n".join(parts)


def _tables_for_error(sql: str, message: str) -> list[str]:
    tables: list[str] = []
    table_match = _NO_SUCH_TABLE_RE.search(message)
    if table_match is not None:
        tables.append(_clean_table_name(table_match.group(1)))
    for match in _TABLE_REF_RE.finditer(sql):
        table = _clean_table_name(match.group(1))
        if table and table not in tables:
            tables.append(table)
    return tables


def _clean_table_name(name: str) -> str:
    name = name.strip().strip('"')
    if "." in name:
        name = name.rsplit(".", 1)[-1].strip('"')
    return name


def _live_columns_for_table(table: str) -> list[tuple[str, str]]:
    if not table:
        return []
    conn = db_helpers.connect()
    try:
        if db_backend.connection_is_postgres(conn):
            rows = conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s "
                "ORDER BY ordinal_position",
                (table,),
            ).fetchall()
            return [(str(row[0]), str(row[1])) for row in rows]
        if not _sqlite_table_exists(conn, table):
            return []
        rows = conn.execute(f'PRAGMA table_info("{_sqlite_ident(table)}")').fetchall()
        return [(str(row[1]), str(row[2])) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _sqlite_table_exists(conn: Any, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _sqlite_ident(identifier: str) -> str:
    return identifier.replace('"', '""')


def _compact_text(text: str, limit: int = 700) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


__all__ = ["schema_hint_for_error"]
