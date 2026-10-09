"""Converge obsolete authority stamps to a neutral scheduling posture."""

from typing import Any

from yoke_contracts.session_queue_posture import SESSION_MODE_DEFAULT
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE


def apply(conn: Any) -> None:
    if not _table_exists(conn, "harness_sessions") or not _column_exists(
        conn, "harness_sessions", "mode"
    ):
        return
    marker = "%s" if connection_is_postgres(conn) else "?"
    conn.execute(
        f"UPDATE harness_sessions SET mode={marker} WHERE mode={marker}",
        (SESSION_MODE_DEFAULT, "operator"),
    )


def invariants(conn: Any) -> None:
    if not _table_exists(conn, "harness_sessions") or not _column_exists(
        conn, "harness_sessions", "mode"
    ):
        return
    if conn.execute(
        "SELECT 1 FROM harness_sessions WHERE mode='operator' LIMIT 1"
    ).fetchone():
        raise RuntimeError(
            "obsolete_session_mode: existing operator modes remain. Recovery: "
            "rehearse mode convergence and boot the candidate before serving."
        )
