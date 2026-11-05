"""Store launch assignments directly instead of parsing a chat name."""

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)

MINIMUM_SERVING_VERSION = NEXT_RELEASE
RETIRES_INVARIANTS = ("0024_session_presentation_and_launch_name",)


def apply(conn: Any) -> None:
    if not _table_exists(conn, "session_launches"):
        return
    _add_column_if_not_exists(
        conn, "session_launches", "item_id", "INTEGER REFERENCES items(id)"
    )
    if not _column_exists(conn, "session_launches", "session_name"):
        return
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT launch_id, project_id, session_name FROM session_launches "
        "WHERE item_id IS NULL AND session_name IS NOT NULL"
    ).fetchall()
    for launch_id, project_id, name in rows:
        reference, separator, _ = name.partition(":")
        if not separator:
            continue
        item = conn.execute(
            "SELECT i.id FROM items i JOIN item_refs r ON r.item_id=i.id "
            f"WHERE i.project_id={p} AND r.public_ref={p}",
            (project_id, reference.strip()),
        ).fetchone()
        if item is not None:
            conn.execute(
                f"UPDATE session_launches SET item_id={p} WHERE launch_id={p}",
                (item[0], launch_id),
            )
    conn.execute("ALTER TABLE session_launches DROP COLUMN session_name")


def invariants(conn: Any) -> None:
    if _table_exists(conn, "harness_sessions"):
        for column in (
            "presentation_surface",
            "presentation_state",
            "presentation_mode",
            "presentation_source",
            "presentation_observed_at",
        ):
            assert _column_exists(conn, "harness_sessions", column)
    if not _table_exists(conn, "session_launches"):
        return
    assert _column_exists(conn, "session_launches", "item_id")
    assert not _column_exists(conn, "session_launches", "session_name")
    assert not conn.execute(
        "SELECT l.launch_id FROM session_launches l LEFT JOIN items i ON i.id=l.item_id "
        "WHERE l.item_id IS NOT NULL AND (i.id IS NULL OR i.project_id<>l.project_id)"
    ).fetchall()
