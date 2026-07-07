"""Render epic task progress notes into item bodies."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.schema_common import (
    _get_columns as _schema_get_columns,
    _table_exists as _schema_table_exists,
)


def _inline_value(value: object) -> str:
    if value is None:
        return "(null)"
    text = str(value)
    if text == "":
        return "(empty)"
    return text.replace("\n", "\\n")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def render_epic_progress_notes_section(
    conn: Any,
    item_id: int,
) -> str:
    """Render all ``epic_progress_notes`` rows for an epic."""
    if not _schema_table_exists(conn, "epic_progress_notes"):
        return ""
    note_columns = _schema_get_columns(conn, "epic_progress_notes")
    if not {"epic_id", "task_num", "note_num"}.issubset(note_columns):
        return ""

    title_select = "COALESCE(t.title, '') AS task_title"
    join_clause = """
        LEFT JOIN epic_tasks t
          ON t.epic_id = n.epic_id AND t.task_num = n.task_num
    """
    if not _schema_table_exists(conn, "epic_tasks"):
        title_select = "'' AS task_title"
        join_clause = ""
    p = _p(conn)
    rows = query_rows(
        conn,
        f"""
        SELECT n.*, {title_select}
        FROM epic_progress_notes n
        {join_clause}
        WHERE n.epic_id = {p}
        ORDER BY n.task_num ASC, n.note_num ASC
        """,
        (item_id,),
    )
    if not rows:
        return ""

    chunks = ["## Epic Progress Notes"]
    for row in rows:
        title = f": {row['task_title']}" if row["task_title"] else ""
        body = str(row["body"] if "body" in note_columns else "").rstrip("\n")
        metadata = "\n".join(
            f"- {column}: {_inline_value(row[column])}"
            for column in note_columns
            if column != "body"
        )
        chunks.append(
            "\n".join([
                f"### Task {row['task_num']} note {row['note_num']}{title}",
                metadata,
                "",
                body,
            ])
        )
    return "\n\n".join(chunks)
