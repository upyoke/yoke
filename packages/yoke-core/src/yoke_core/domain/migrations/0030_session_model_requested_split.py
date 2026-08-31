"""Move requested-era session model echoes out of the served-truth column.

Before this entry, ``harness_sessions.model`` stored whatever was asked for
— a Yoke launch's ``--model``, an env override, a Claude context-tier
selector such as ``claude-opus-5[1m]`` that no provider response ever
returns — while every reader treated it as what actually ran. The column
now holds only provider-attested truth, so each existing value moves to
``requested_model``, where it is exactly what it always was, and ``model``
is cleared for those rows rather than left asserting a fact nobody checked.

Idempotent against its own output: a row already carrying
``requested_model`` is finished and is not rewritten, so a replay of the
history over a converged database is a no-op rather than a second move that
would blank a genuinely attested value.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)


# A build older than this entry reads harness_sessions.model as the
# session's model and inserts it NOT NULL; against a converged database it
# would report every pre-cutover session as having no model at all.
MINIMUM_SERVING_VERSION = NEXT_RELEASE

TABLE = "harness_sessions"
REQUESTED_COLUMNS = (
    ("requested_model", "TEXT DEFAULT NULL"),
    ("requested_reasoning_effort", "TEXT DEFAULT NULL"),
    ("requested_context_window_tokens", "INTEGER DEFAULT NULL"),
)
SERVED_COLUMNS = (
    ("reasoning_effort", "TEXT DEFAULT NULL"),
    ("context_window_tokens", "INTEGER DEFAULT NULL"),
)


def apply(conn: Any) -> None:
    if not _table_exists(conn, TABLE):
        return
    for column, ddl in REQUESTED_COLUMNS + SERVED_COLUMNS:
        _add_column_if_not_exists(conn, TABLE, column, ddl)
    _drop_model_not_null(conn)
    # Only rows that have not already been moved: requested_model IS NULL is
    # the "untouched" marker, and it is exactly the state this entry leaves
    # behind for a row that never carried a model in the first place.
    # NULLIF because a blank is not a model: it names neither an ask nor
    # anything a provider served, so it moves to nothing rather than
    # becoming a blank request.
    conn.execute(
        f"UPDATE {TABLE} SET requested_model = NULLIF(model, ''), model = NULL "
        "WHERE requested_model IS NULL AND model IS NOT NULL"
    )


def _drop_model_not_null(conn: Any) -> None:
    """Relax the served-truth column so "not attested" is expressible.

    Only the Postgres authority can hold the pre-cutover shape: a SQLite
    surface builds this table from the current DDL, which already declares
    the column nullable, and SQLite cannot alter a constraint in place
    anyway.
    """
    if not db_backend.connection_is_postgres(conn):
        return
    conn.execute(f"ALTER TABLE {TABLE} ALTER COLUMN model DROP NOT NULL")


def invariants(conn: Any) -> None:
    assert _table_exists(conn, TABLE), "harness sessions table is missing"
    for column, _ddl in REQUESTED_COLUMNS + SERVED_COLUMNS:
        assert _column_exists(conn, TABLE, column), (
            f"{TABLE}.{column} is missing after the requested/served split"
        )
    stranded = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} "
        "WHERE requested_model IS NULL AND model IS NOT NULL"
    ).fetchone()
    assert int(stranded[0]) == 0, (
        "harness_sessions rows still hold a model with no requested_model"
    )


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
