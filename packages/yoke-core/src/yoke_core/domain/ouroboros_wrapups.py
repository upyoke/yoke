"""Ouroboros wrapup report persistence and rendering."""
from __future__ import annotations

import os

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import (
    iso8601_now,
    query_one,
    query_rows,
)
from yoke_core.domain.schema_init_apply import execute_schema_script

__all__ = [
    "cmd_generate_wrapup",
    "cmd_insert_wrapup",
    "cmd_list_wrapups",
]

_WRAPUP_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS wrapup_reports (
    id INTEGER PRIMARY KEY,
    session_timestamp TEXT NOT NULL UNIQUE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _format_row(row) -> str:
    return "|".join("" if value is None else str(value) for value in tuple(row))


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _resolve_wrapups_dir() -> str:
    from yoke_core.domain.db_helpers import resolve_db_path
    from yoke_core.domain.schema import guard_state_dir_creation

    db_path = resolve_db_path()
    yoke_root = os.path.dirname(db_path)
    wrapups_dir = os.path.join(yoke_root, "ouroboros", "wrapups")
    guard_state_dir_creation(wrapups_dir, "ouroboros._resolve_wrapups_dir")
    return wrapups_dir


def _ensure_wrapup_table(conn) -> None:
    execute_schema_script(conn, _WRAPUP_TABLE_SQL)


def cmd_insert_wrapup(conn, session_timestamp: str, body: str) -> str:
    _ensure_wrapup_table(conn)

    existing = query_one(
        conn,
        f"SELECT id FROM wrapup_reports WHERE session_timestamp={_p(conn)}",
        (session_timestamp,),
    )
    if existing:
        p = _p(conn)
        conn.execute(
            f"UPDATE wrapup_reports SET body={p} WHERE session_timestamp={p}",
            (body, session_timestamp),
        )
        conn.commit()
        return str(existing["id"])

    p = _p(conn)
    cursor = conn.execute(
        "INSERT INTO wrapup_reports (session_timestamp, body, created_at) "
        f"VALUES ({p}, {p}, {p}) RETURNING id",
        (session_timestamp, body, iso8601_now()),
    )
    wrapup_id = int(cursor.fetchone()[0])
    conn.commit()
    return str(wrapup_id)


def cmd_list_wrapups(conn) -> str:
    _ensure_wrapup_table(conn)
    rows = query_rows(
        conn,
        "SELECT id, session_timestamp, created_at "
        "FROM wrapup_reports ORDER BY session_timestamp DESC",
    )
    return "\n".join(_format_row(row) for row in rows)


def cmd_generate_wrapup(conn, session_timestamp: str) -> str:
    _ensure_wrapup_table(conn)

    row = query_one(
        conn,
        f"SELECT body FROM wrapup_reports WHERE session_timestamp={_p(conn)}",
        (session_timestamp,),
    )
    if row is None:
        raise LookupError(f"no wrapup found for session_timestamp '{session_timestamp}'")

    body = row["body"]
    wrapups_dir = _resolve_wrapups_dir()
    os.makedirs(wrapups_dir, exist_ok=True)
    output_file = os.path.join(wrapups_dir, f"{session_timestamp}.md")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(body)
        if not body.endswith("\n"):
            f.write("\n")

    return f"Generated: {output_file}"
