"""Ouroboros entry creation, querying, and review/archive lifecycle."""

from __future__ import annotations

from yoke_core.domain.field_note_correlations import attach_correlations
from typing import Optional

from yoke_contracts.timestamps import format_instant, utc_now

from yoke_core.domain.ouroboros_entry_insert import cmd_insert_entry
from yoke_core.domain import db_backend
from yoke_core.domain.ouroboros_entry_presentation import (
    _apply_correction_link,
    _format_row,
    entry_wire_value,
)
from yoke_core.domain.db_helpers import (
    instant_parameter,
    query_one,
    query_rows,
    query_scalar,
)
from yoke_core.domain.field_note_dash_promotion import (
    promoted_dash_by_field_note_ids,
)
from yoke_core.domain.ouroboros_entry_corrections import (
    correction_links_by_entry_ids,
)
from yoke_core.domain.ouroboros_entry_write_scope import (
    project_scope_predicate,
    require_bulk_scope_project_id,
    require_entry_writable_by_project,
    resolve_scope_project_id,
)
from yoke_core.domain.project_identity import resolve_project_id

__all__ = [
    "DEFAULT_ENTRY_LIST_LIMIT",
    "ENTRY_LIST_COLUMNS",
    "MAX_ENTRY_LIST_LIMIT",
    "cmd_insert_entry",
    "cmd_list_entries",
    "cmd_mark_archived",
    "cmd_mark_reviewed",
    "count_entry_rows",
    "get_entry_row",
    "list_entry_rows",
]


DEFAULT_ENTRY_LIST_LIMIT = 50
MAX_ENTRY_LIST_LIMIT = 500

ENTRY_LIST_COLUMNS = (
    "id",
    "timestamp",
    "agent",
    "category",
    "body",
    "reviewed_at",
    "project",
    "actor_id", "reporter_email", "yoke_version", "universe_fingerprint",
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _entry_list_filters(
    conn,
    *,
    unreviewed: bool,
    project: Optional[str],
    category: Optional[str],
    project_ids=None, include_unscoped=False,
) -> tuple[str, list[object]]:
    """Shared WHERE clause + params for list and count projections."""
    p = _p(conn)
    conditions: list[str] = []
    params: list[object] = []

    if unreviewed:
        conditions.append(
            "o.reviewed_at IS NULL AND o.archived_at IS NULL AND o.correlation_id IS NULL"
        )
    if project_ids is not None:
        from yoke_core.domain.handlers.ouroboros_roster_scope import scope_predicate
        clause, ids = scope_predicate(conn, project_ids, include_unscoped)
        conditions.append(clause)
        params.extend(ids)
    elif project:
        conditions.append(f"o.project_id={p}")
        params.append(resolve_project_id(conn, project))
    if category:
        conditions.append(f"o.category= {p}")
        params.append(category)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


def _bounded_limit(limit: Optional[int]) -> int:
    if limit is None:
        return DEFAULT_ENTRY_LIST_LIMIT
    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > MAX_ENTRY_LIST_LIMIT:
        raise ValueError(f"limit must be <= {MAX_ENTRY_LIST_LIMIT}")
    return limit


def _bounded_offset(offset: int) -> int:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    return offset


def list_entry_rows(
    conn,
    unreviewed: bool = False,
    project: Optional[str] = None,
    category: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    project_ids=None, include_unscoped=False,
) -> list[dict]:
    """Typed entry rows; shared by the CLI renderer and ouroboros.field_note.list.

    Always newest-first and bounded (default
    :data:`DEFAULT_ENTRY_LIST_LIMIT`) so the https relay cannot exceed its
    response size ceiling on a large unreviewed queue.
    """
    p = _p(conn)
    where, params = _entry_list_filters(
        conn,
        unreviewed=unreviewed,
        project=project,
        category=category,
        project_ids=project_ids, include_unscoped=include_unscoped,
    )
    bound = _bounded_limit(limit)
    skip = _bounded_offset(offset)
    params.extend([bound, skip])
    rows = query_rows(
        conn,
        "SELECT o.id, o.timestamp, o.agent, "
        "o.category, o.body, o.reviewed_at, "
        "COALESCE(p.slug,''), o.actor_id, o.reporter_email, o.yoke_version, o.universe_fingerprint "
        "FROM ouroboros_entries o "
        "LEFT JOIN projects p ON p.id = o.project_id "
        f"{where} ORDER BY o.id DESC LIMIT {p} OFFSET {p}",
        tuple(params),
    )
    entries = [
        {
            name: entry_wire_value(name, value)
            for name, value in zip(ENTRY_LIST_COLUMNS, tuple(row))
        }
        for row in rows
    ]
    promotions = promoted_dash_by_field_note_ids(
        conn,
        (entry["id"] for entry in entries),
    )
    links = correction_links_by_entry_ids(
        conn,
        (entry["id"] for entry in entries),
    )
    for entry in entries:
        entry["promoted_dash"] = promotions.get(entry["id"])
        _apply_correction_link(entry, links.get(entry["id"]))
    attach_correlations(conn, entries)
    return entries


def count_entry_rows(
    conn,
    unreviewed: bool = False,
    project: Optional[str] = None,
    category: Optional[str] = None,
    project_ids=None, include_unscoped=False,
) -> int:
    """Matching row count for the same filters as :func:`list_entry_rows`."""
    where, params = _entry_list_filters(
        conn,
        unreviewed=unreviewed,
        project=project,
        category=category,
        project_ids=project_ids, include_unscoped=include_unscoped,
    )
    total = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM ouroboros_entries o {where}",
        tuple(params),
    )
    return int(total or 0)


def cmd_list_entries(
    conn,
    unreviewed: bool = False,
    project: Optional[str] = None,
    category: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> str:
    return "\n".join(
        _format_row([row[name] for name in ENTRY_LIST_COLUMNS[:7]])
        for row in list_entry_rows(
            conn,
            unreviewed,
            project,
            category,
            limit,
            offset,
        )
    )


def get_entry_row(conn, entry_id: int) -> Optional[dict]:
    """One typed entry by id (full body, plus archived_at), or ``None``."""
    p = _p(conn)
    row = query_one(
        conn,
        "SELECT o.id, o.timestamp, o.agent, "
        "o.category, o.body, o.reviewed_at, "
        "COALESCE(p.slug,''), o.actor_id, o.reporter_email, o.yoke_version, o.universe_fingerprint, o.archived_at "
        "FROM ouroboros_entries o "
        "LEFT JOIN projects p ON p.id = o.project_id "
        f"WHERE o.id={p}",
        (entry_id,),
    )
    if row is None:
        return None
    names = (*ENTRY_LIST_COLUMNS, "archived_at")
    entry = {
        name: entry_wire_value(name, value) for name, value in zip(names, tuple(row))
    }
    entry["promoted_dash"] = promoted_dash_by_field_note_ids(
        conn,
        [entry_id],
    ).get(entry_id)
    _apply_correction_link(
        entry,
        correction_links_by_entry_ids(conn, [entry_id]).get(entry_id),
    )
    attach_correlations(conn, [entry])
    return entry


def _entry_write_where(conn, entry_id: int, project: Optional[str]) -> tuple:
    """Build the ``WHERE`` confining a write to one named entry."""
    project_id = resolve_scope_project_id(conn, project)
    require_entry_writable_by_project(conn, entry_id, project_id)
    scope_sql, scope_params = project_scope_predicate(
        conn,
        project_id,
        include_unattributed=True,
    )
    where = f"id={_p(conn)}"
    if scope_sql:
        where += f" AND {scope_sql}"
    return where, (entry_id, *scope_params)


def cmd_mark_reviewed(conn, entry_id: int, project: Optional[str] = None) -> str:
    p = _p(conn)
    where, where_params = _entry_write_where(conn, entry_id, project)
    ts = utc_now()
    conn.execute(
        f"UPDATE ouroboros_entries SET reviewed_at={p} WHERE {where}",
        (instant_parameter(conn, ts), *where_params),
    )
    conn.commit()
    return f"Marked entry {entry_id} as reviewed at {format_instant(ts)}"


def cmd_mark_archived(
    conn,
    entry_id: Optional[int] = None,
    all_reviewed: bool = False,
    project: Optional[str] = None,
    include_unattributed: bool = False,
) -> str:
    p = _p(conn)
    ts = utc_now()
    if all_reviewed:
        scope_sql, scope_params = project_scope_predicate(
            conn,
            require_bulk_scope_project_id(conn, project),
            include_unattributed=include_unattributed,
        )
        where = f"{scope_sql} AND reviewed_at IS NOT NULL AND archived_at IS NULL"
        count = query_scalar(
            conn,
            f"SELECT COUNT(*) FROM ouroboros_entries WHERE {where}",
            scope_params,
        )
        if not count:
            return "0"
        conn.execute(
            f"UPDATE ouroboros_entries SET archived_at={p} WHERE {where}",
            (instant_parameter(conn, ts), *scope_params),
        )
        conn.commit()
        return str(count)

    if entry_id is None:
        raise ValueError("entry ID required")
    where, where_params = _entry_write_where(conn, entry_id, project)
    conn.execute(
        f"UPDATE ouroboros_entries SET archived_at={p} WHERE {where}",
        (instant_parameter(conn, ts), *where_params),
    )
    conn.commit()
    return "1"
