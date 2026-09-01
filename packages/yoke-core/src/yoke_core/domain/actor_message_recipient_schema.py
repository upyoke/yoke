"""The two recipient kinds that share the non-session recipient table.

An ACTOR row is one person's read state in their inbox. A STEERING row is a
message addressed to the steering ROLE: it parks when no seat covers it, is
handed to the seat that does, and is acknowledged there. They share a table
because both answer the same question -- who else, apart from a live
session, is this message for -- while tracking different lifecycles.

Sharing is only safe because the compound constraint below keeps each kind
inside its own vocabulary: neither may borrow the other's states, and each
declares the columns it cannot be meaningful without. A database born
before the steering kind converges to the same shape additively -- the
actor becomes optional, the extra columns appear, and the named constraint
replaces the narrower state check the table first shipped with.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists


TABLE = "actor_message_recipients"

#: The compound contract that keeps two recipient kinds honest in one table.
RECIPIENT_KIND_STATE_CONSTRAINT = "actor_message_recipient_kind_state"

#: Read states for a person reading their inbox.
ACTOR_RECIPIENT_STATES = ("pending", "read", "expired")

#: Seat states for a message addressed to the steering ROLE: it waits for a
#: seat, is handed to the one that covers it, and is acknowledged there.
STEERING_RECIPIENT_STATES = ("awaiting_seat", "delivered", "acknowledged")


def _quoted(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


RECIPIENT_KIND_STATE_PREDICATE = (
    "(recipient_kind = 'actor' AND actor_id IS NOT NULL AND state IN "
    f"({_quoted(ACTOR_RECIPIENT_STATES)})) OR "
    "(recipient_kind = 'steering' AND actor_id IS NULL "
    "AND project_id IS NOT NULL AND steering_scope IS NOT NULL "
    f"AND state IN ({_quoted(STEERING_RECIPIENT_STATES)}))"
)

#: Columns the steering recipient kind adds beside the actor read state.
_STEERING_RECIPIENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("recipient_kind", "TEXT NOT NULL DEFAULT 'actor'"),
    ("steering_scope", "TEXT"),
    ("sender_item_id", "INTEGER REFERENCES items(id)"),
    ("project_id", "INTEGER REFERENCES projects(id)"),
    ("seat_session_id", "TEXT REFERENCES harness_sessions(session_id)"),
    ("seat_claim_id", "INTEGER REFERENCES work_claims(id)"),
    ("delivered_at", "TEXT"),
    ("acknowledged_at", "TEXT"),
)

#: The state check the table shipped with before it carried a second kind.
_RETIRED_STATE_CONSTRAINT = "actor_message_recipients_state_check"


def _converge_postgres_shape(conn: Any) -> None:
    """Relax the actor-only column and constraint shape in place.

    Only Postgres can alter a column's nullability or replace a constraint;
    a validation-surface SQLite fixture is always born from the create
    script above and already has the final shape.
    """
    for column, column_ddl in _STEERING_RECIPIENT_COLUMNS:
        if not _column_exists(conn, TABLE, column):
            conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {column} {column_ddl}")
    conn.execute(f"ALTER TABLE {TABLE} ALTER COLUMN actor_id DROP NOT NULL")
    conn.execute(
        f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {_RETIRED_STATE_CONSTRAINT}"
    )
    present = conn.execute(
        "SELECT 1 FROM pg_constraint "
        f"WHERE conrelid='{TABLE}'::regclass AND conname=%s",
        (RECIPIENT_KIND_STATE_CONSTRAINT,),
    ).fetchone()
    if present is None:
        conn.execute(
            f"ALTER TABLE {TABLE} ADD CONSTRAINT "
            f"{RECIPIENT_KIND_STATE_CONSTRAINT} CHECK "
            f"({RECIPIENT_KIND_STATE_PREDICATE})"
        )


def converge_role_addressed_recipients(conn: Any) -> None:
    """Widen an actor-only recipient table to hold role-addressed rows too.

    Every statement that names a steering column lives here rather than in
    the create script, because the create script also runs against a table
    that predates those columns: an index declared beside the table would
    reference a column this function has not added yet.
    """
    if db_backend.connection_is_postgres(conn):
        _converge_postgres_shape(conn)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_actor_message_recipients_steering "
        f"ON {TABLE}(message_id) WHERE recipient_kind = 'steering'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_actor_message_recipients_seat "
        f"ON {TABLE}(project_id, state, created_at) "
        "WHERE recipient_kind = 'steering'"
    )


__all__ = [
    "ACTOR_RECIPIENT_STATES",
    "RECIPIENT_KIND_STATE_CONSTRAINT",
    "RECIPIENT_KIND_STATE_PREDICATE",
    "STEERING_RECIPIENT_STATES",
    "TABLE",
    "converge_role_addressed_recipients",
]
