"""Retire surfaces whose authority moved elsewhere.

Each column here was replaced by a different representation and is no longer
read or written by any code path:

- ``items.worktree``, ``epic_tasks.worktree`` / ``worktree_path`` / ``branch``
  — worktree identity became a row in ``item_worktrees``, referenced by
  ``item_worktree_id``.
- ``items.flow`` — superseded by ``deployment_flow``.
- ``items.type`` — superseded by the pinned ``workflow_id``.
- ``items.browser_qa_metadata`` — superseded by the QA tables.
- ``events.parent_id``, ``events.user_id`` — superseded by ``actor_id``.
- ``epic_tasks.blocked_by`` — superseded by ``item_dependencies`` rows.
- ``path_claims.session_id`` / ``item_id`` / ``work_claim_id`` / ``actor_id``
  — superseded by the typed owner triple (``owner_kind`` plus the matching
  ``owner_item_id`` / ``owner_session_id`` / ``owner_work_claim_id``), with
  registration provenance on ``registered_by_*``.

These drops already reached the authoritative installs through the mechanism
that predated the ordered history — the one that applied a module by hand and
then deleted its source. That is exactly why this entry exists: any universe
born before those drops and never named as a dispatch target still carries
the columns, with nothing in the system able to notice. Recording the change
as ordered history makes it reach every database instead of the ones someone
remembered to list.

Guarded throughout, so this is a no-op wherever it already landed.
"""

from __future__ import annotations

from typing import Any

#: ``(table, column)`` pairs to retire, grouped by the surface that replaced
#: them. Order is irrelevant — each drop is independent.
SUPERSEDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("items", "worktree"),
    ("items", "flow"),
    ("items", "type"),
    ("items", "browser_qa_metadata"),
    ("events", "parent_id"),
    ("events", "user_id"),
    ("epic_tasks", "blocked_by"),
    ("epic_tasks", "branch"),
    ("epic_tasks", "worktree"),
    ("epic_tasks", "worktree_path"),
    ("path_claims", "session_id"),
    ("path_claims", "item_id"),
    ("path_claims", "work_claim_id"),
    ("path_claims", "actor_id"),
)

#: Whole tables whose authority moved. ``wrapup_reports`` held session
#: wrap-up records; that content lives on items now.
SUPERSEDED_TABLES: tuple[str, ...] = ("wrapup_reports",)


def apply(conn: Any) -> None:
    """Drop each superseded surface that is still present.

    Guards with an explicit existence check rather than ``DROP ... IF
    EXISTS``, which Postgres accepts and SQLite does not — the generic SQLite
    validation surface has to be able to run this too.
    """
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    for table, column in SUPERSEDED_COLUMNS:
        if not _table_exists(conn, table):
            continue
        if not _column_exists(conn, table, column):
            continue
        conn.execute(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')

    for table in SUPERSEDED_TABLES:
        if _table_exists(conn, table):
            conn.execute(f'DROP TABLE "{table}"')


def invariants(conn: Any) -> None:
    """Prove no superseded surface survives."""
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    for table, column in SUPERSEDED_COLUMNS:
        if not _table_exists(conn, table):
            continue
        if _column_exists(conn, table, column):
            raise AssertionError(
                f"{table}.{column} is superseded but still present"
            )
    for table in SUPERSEDED_TABLES:
        if _table_exists(conn, table):
            raise AssertionError(f"{table} is superseded but still present")


__all__ = ["SUPERSEDED_COLUMNS", "SUPERSEDED_TABLES", "apply", "invariants"]
