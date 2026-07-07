"""Catalog helpers for the raw-SQL escape hatch."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

_PG_UNDEFINED_COLUMN_RE = re.compile(
    r"column (?:(\w+)\.)?(\w+) does not exist", re.IGNORECASE
)
_PG_UNDEFINED_RELATION_RE = re.compile(
    r"relation [\"']?(\w+)[\"']? does not exist", re.IGNORECASE
)


def match_pg_undefined_column(msg: str) -> Optional[Tuple[Optional[str], str]]:
    match = _PG_UNDEFINED_COLUMN_RE.search(msg)
    return match.groups() if match else None


def match_pg_undefined_relation(msg: str) -> Optional[str]:
    match = _PG_UNDEFINED_RELATION_RE.search(msg)
    return match.group(1) if match else None


def columns_for_table(conn: Any, table: str) -> List[str]:
    try:
        rows = conn.execute(
            "SELECT a.attname "
            "FROM pg_attribute AS a "
            "WHERE a.attrelid = to_regclass(%s) "
            "  AND a.attnum > 0 "
            "  AND NOT a.attisdropped "
            "ORDER BY a.attnum",
            (table,),
        ).fetchall()
    except Exception:
        return []
    return [str(r[0]) for r in rows]


def all_table_names(conn: Any) -> List[str]:
    try:
        rows = conn.execute(
            "SELECT c.relname "
            "FROM pg_class AS c "
            "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p') "
            "  AND n.nspname = ANY(current_schemas(true)) "
            "ORDER BY c.relname"
        ).fetchall()
    except Exception:
        return []
    return [str(r[0]) for r in rows]
