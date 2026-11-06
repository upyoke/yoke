"""Store launch assignments directly instead of parsing a chat name."""

from importlib import import_module
from typing import Any

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)

MINIMUM_SERVING_VERSION = NEXT_RELEASE
RETIRES_INVARIANTS = (
    "0024_session_presentation_and_launch_name",
    "0071_model_effort_levels",
)


def apply(conn: Any) -> None:
    if _table_exists(conn, "harness_sessions"):
        _add_column_if_not_exists(conn, "harness_sessions", "harness_title", "TEXT")
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
    _model_level_invariants(conn)
    if _table_exists(conn, "harness_sessions"):
        for column in (
            "harness_title",
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


def _model_level_invariants(conn: Any) -> None:
    """Retain the model-level proofs using the structured launch assignment."""
    levels = import_module("yoke_core.domain.migrations.0071_model_effort_levels")
    if _table_exists(conn, "session_launches") and _column_exists(
        conn, "session_launches", "level_placement"
    ):
        for launch_id, raw in conn.execute(
            "SELECT launch_id,level_placement FROM session_launches "
            "WHERE requested_level IS NOT NULL OR item_id IS NOT NULL"
        ).fetchall():
            assert json_helper.loads_text(str(raw)) == levels._work_placement(raw), (
                f"launch {launch_id} has unconverged work purpose"
            )
    for table, _, key, raw in levels._documents(conn):
        assert json_helper.loads_text(str(raw)) == levels._decode(table, key, raw), (
            f"{table} row {key} has unconverged levels"
        )
    if _table_exists(conn, "universe_settings"):
        from yoke_core.domain.quota_pool_order import read_pool_order

        read_pool_order(conn)
