"""Project scoping for writes against the Ouroboros learning queue.

One rule, applied by every entry write:

* An **entry-targeted** write (one ``entry_id``) is authorized and confined
  by the ENTRY row's own ``project_id``. A project named by the caller —
  ``--project``, ``YOKE_PROJECT``, or the checkout map — is a confinement
  filter, never a redirect: it must agree with an attributed row, and it
  supplies authority only for an *unattributed* row, which belongs to no
  project. Naming the single id is itself the opt-in for that row.
* A **bulk** selector (a date cutoff, or every reviewed entry) always
  requires a named project, so no call can sweep the whole universe. It
  covers only that project's rows unless the caller explicitly opts into
  unattributed rows as well.

``project_id IS NULL`` means the entry belongs to no project, so no
project's grant covers it implicitly. Bulk callers reach those rows with
``include_unattributed``; the default leaves them alone rather than
silently sweeping the universe-global backlog into one project's run.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.project_identity import resolve_project_id


class CrossProjectEntryWrite(ValueError):
    """A named project does not own the entry the write targets."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def resolve_scope_project_id(conn: Any, project: Optional[str]) -> Optional[int]:
    """Resolve a caller-named project to its id, or ``None`` when unnamed."""
    if project is None or not str(project).strip():
        return None
    return resolve_project_id(conn, project)


def project_scope_predicate(
    conn: Any,
    project_id: Optional[int],
    *,
    include_unattributed: bool,
) -> tuple[str, tuple[Any, ...]]:
    """Return the ``(sql, params)`` confining a write to one project's rows.

    An unnamed project yields an empty fragment: the caller has already
    established authority some other way (the entry row itself), and no
    further narrowing applies.
    """
    if project_id is None:
        return "", ()
    p = _p(conn)
    if include_unattributed:
        return f"(project_id={p} OR project_id IS NULL)", (project_id,)
    return f"project_id={p}", (project_id,)


def require_bulk_scope_project_id(conn: Any, project: Optional[str]) -> int:
    """Resolve the project a bulk selector runs against; refuse an unbounded run."""
    project_id = resolve_scope_project_id(conn, project)
    if project_id is None:
        raise ValueError(
            "a bulk Ouroboros write must name its project: pass --project P, "
            "set YOKE_PROJECT, or run from a registered checkout"
        )
    return project_id


def require_entry_writable_by_project(
    conn: Any,
    entry_id: int,
    project_id: Optional[int],
) -> None:
    """Refuse an entry-targeted write aimed at another project's entry.

    Raises ``LookupError`` when the entry does not exist and
    ``CrossProjectEntryWrite`` when it belongs to a project other than the
    one the caller named. An unattributed entry is writable by the named
    project: no other project's row is at risk, and refusing it would strand
    every entry filed before or outside project attribution.
    """
    p = _p(conn)
    row = query_one(
        conn,
        "SELECT o.project_id, COALESCE(p.slug, '') "
        "FROM ouroboros_entries o "
        "LEFT JOIN projects p ON p.id = o.project_id "
        f"WHERE o.id={p}",
        (entry_id,),
    )
    if row is None:
        raise LookupError(f"entry {entry_id} not found")
    if project_id is None or row[0] is None:
        return
    if int(row[0]) != int(project_id):
        raise CrossProjectEntryWrite(
            f"entry {entry_id} belongs to project {row[1] or row[0]}; "
            "an Ouroboros entry write is authorized by the entry's own "
            "project, not the caller's"
        )


__all__ = [
    "CrossProjectEntryWrite",
    "project_scope_predicate",
    "require_bulk_scope_project_id",
    "require_entry_writable_by_project",
    "resolve_scope_project_id",
]
