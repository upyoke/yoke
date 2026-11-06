"""Persist whether Yoke launched a session before permitting native resumes."""

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists, _table_exists


def apply(conn: Any) -> None:
    if not _table_exists(conn, "harness_sessions"):
        return
    _add_column_if_not_exists(
        conn,
        "harness_sessions",
        "launch_origin",
        "TEXT NOT NULL DEFAULT 'operator' CHECK (launch_origin IN ('yoke','operator'))",
    )
    if _table_exists(conn, "session_launches"):
        conn.execute(
            "UPDATE harness_sessions SET launch_origin='yoke' "
            "WHERE launch_origin='operator' AND EXISTS ("
            "SELECT 1 FROM session_launches l WHERE "
            "l.registered_session_id=harness_sessions.session_id OR "
            "l.native_session_id=harness_sessions.session_id OR "
            "l.native_session_id=harness_sessions.native_thread_id)"
        )


def invariants(conn: Any) -> None:
    if _table_exists(conn, "harness_sessions"):
        assert not conn.execute(
            "SELECT 1 FROM harness_sessions "
            "WHERE launch_origin IS NULL OR launch_origin NOT IN ('yoke','operator')"
        ).fetchall()
