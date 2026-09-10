"""Admit the merge boundary's own CI run into the CI-wait vocabulary.

The merge gate's post-rebase verification (`merge_worktree_tests_ci.py`)
dispatches or attaches to a CI run and polls it synchronously, so a worker
whose turn ends mid-poll had nothing recording that it was owed the
verdict: the pytest-selection tool and the QA case runner already record
a durable wait when they dispatch, but the merge boundary's own CI run did
not, leaving it as the one CI-dispatching gate a stopped turn could never
be woken from. `session_ci_run_waits.kind` carries a CHECK constraint
listing the kinds a database accepts, and a table that already exists
keeps the constraint it was created with, so a live universe would refuse
the merge boundary's very first recorded wait until this entry widens it.

Adding a permitted value invalidates no stored row and breaks no reader,
so a build running ahead of this entry and one running behind it both
serve the same data correctly — no ``MINIMUM_SERVING_VERSION`` is needed.
The kind vocabulary is written here rather than imported from
``session_ci_wait_schema``, because a history entry has to load from
whatever build applies it, including a restored archive replaying its
history.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists

WAIT_TABLE = "session_ci_run_waits"
KIND_CONSTRAINT = "session_ci_run_waits_kind_check"

#: The complete kind vocabulary after this entry.
ALL_KINDS = ("selection", "qa_case", "merge_verification")


def _widen_kind_check(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        return
    kinds = ", ".join(f"'{kind}'" for kind in ALL_KINDS)
    escaped = KIND_CONSTRAINT.replace('"', '""')
    conn.execute(
        f'ALTER TABLE "{WAIT_TABLE}" DROP CONSTRAINT IF EXISTS "{escaped}"'
    )
    conn.execute(
        f'ALTER TABLE "{WAIT_TABLE}" ADD CONSTRAINT "{escaped}" '
        f"CHECK(kind IN ({kinds}))"
    )


def apply(conn: Any) -> None:
    if not _table_exists(conn, WAIT_TABLE):
        return
    _widen_kind_check(conn)


def invariants(conn: Any) -> None:
    """Assert the constraint this entry widened still admits every kind.

    Postgres-only, mirroring ``apply``: a non-Postgres database created its
    table fresh from the current schema module and never carried the old
    constraint to widen.
    """
    if not _table_exists(conn, WAIT_TABLE) or not db_backend.connection_is_postgres(
        conn
    ):
        return
    row = conn.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
        (KIND_CONSTRAINT,),
    ).fetchone()
    assert row is not None, f"{KIND_CONSTRAINT} is missing after apply"
    definition = str(row[0])
    for kind in ALL_KINDS:
        assert f"'{kind}'" in definition, (
            f"{KIND_CONSTRAINT} does not admit {kind!r}: {definition}"
        )


__all__ = ["ALL_KINDS", "KIND_CONSTRAINT", "WAIT_TABLE", "apply", "invariants"]
