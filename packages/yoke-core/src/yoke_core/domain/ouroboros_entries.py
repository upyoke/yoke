"""Ouroboros entry creation, querying, and review/archive lifecycle."""
from __future__ import annotations

from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import (
    iso8601_now,
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


# Bound the shared reader so https relay payloads stay under the size limit.
# Newest-first paging uses the same default when callers omit --limit.
DEFAULT_ENTRY_LIST_LIMIT = 50
MAX_ENTRY_LIST_LIMIT = 500

# Result names for the entry-list projection, in SELECT order.
ENTRY_LIST_COLUMNS = (
    "id", "timestamp", "agent", "context", "category", "body",
    "reviewed_at", "project",
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _format_row(row) -> str:
    # Collapse newlines to spaces so each row stays a single ``|``-joined
    # line. Done in Python rather than SQL: the SQLite ``char(10)`` newline
    # idiom is not portable (Postgres parses ``char(10)`` as a type cast,
    # not a newline literal), so newline normalization lives here instead.
    return "|".join(
        "" if value is None else str(value).replace("\n", " ")
        for value in tuple(row)
    )


def _apply_correction_link(entry: dict, link: Optional[dict]) -> None:
    """Project both supersede directions onto an entry, absent as None."""
    entry["corrects"] = (link or {}).get("corrects")
    entry["superseded_by"] = (link or {}).get("superseded_by")


def cmd_insert_entry(
    conn,
    timestamp: str,
    agent: str,
    context: Optional[str],
    category: str,
    body: str,
    project: Optional[str] = None,
) -> str:
    p = _p(conn)
    project_id = resolve_project_id(conn, project) if project else None
    existing = query_one(
        conn,
        "SELECT id FROM ouroboros_entries "
        f"WHERE timestamp={p} AND agent={p} AND category={p} AND body={p}",
        (timestamp, agent, category, body),
    )
    if existing:
        return "Duplicate entry skipped"

    # Native id read: driver-side generated-id attributes are fragile to
    # intervening sequence touches. RETURNING is the unambiguous form.
    row = conn.execute(
        "INSERT INTO ouroboros_entries "
        "(timestamp, agent, context, category, body, project_id, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
        (timestamp, agent, context, category, body, project_id, iso8601_now()),
    ).fetchone()
    conn.commit()
    return str(row[0])


def _entry_list_filters(
    conn,
    *,
    unreviewed: bool,
    project: Optional[str],
    category_prefix: Optional[str],
) -> tuple[str, list[object]]:
    """Shared WHERE clause + params for list and count projections."""
    p = _p(conn)
    conditions: list[str] = []
    params: list[object] = []

    if unreviewed:
        conditions.append("o.reviewed_at IS NULL AND o.archived_at IS NULL")
    if project:
        conditions.append(f"o.project_id={p}")
        params.append(resolve_project_id(conn, project))
    if category_prefix:
        conditions.append(f"o.category LIKE {p}")
        params.append(f"{category_prefix}%")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


def _bounded_limit(limit: Optional[int]) -> int:
    if limit is None:
        return DEFAULT_ENTRY_LIST_LIMIT
    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > MAX_ENTRY_LIST_LIMIT:
        raise ValueError(
            f"limit must be <= {MAX_ENTRY_LIST_LIMIT}"
        )
    return limit


def _bounded_offset(offset: int) -> int:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    return offset


def list_entry_rows(
    conn,
    unreviewed: bool = False,
    project: Optional[str] = None,
    category_prefix: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list[dict]:
    """Typed entry rows; shared by the CLI renderer and ouroboros.entry.list.

    Always newest-first and bounded (default
    :data:`DEFAULT_ENTRY_LIST_LIMIT`) so the https relay cannot exceed its
    response size ceiling on a large unreviewed queue.
    """
    p = _p(conn)
    where, params = _entry_list_filters(
        conn,
        unreviewed=unreviewed,
        project=project,
        category_prefix=category_prefix,
    )
    bound = _bounded_limit(limit)
    skip = _bounded_offset(offset)
    params.extend([bound, skip])
    rows = query_rows(
        conn,
        "SELECT o.id, o.timestamp, o.agent, COALESCE(o.context,''), "
        "o.category, o.body, COALESCE(o.reviewed_at,''), "
        "COALESCE(p.slug,'') "
        "FROM ouroboros_entries o "
        "LEFT JOIN projects p ON p.id = o.project_id "
        f"{where} ORDER BY o.id DESC LIMIT {p} OFFSET {p}",
        tuple(params),
    )
    entries = [
        {
            name: (int(value) if name == "id"
                   else "" if value is None else str(value))
            for name, value in zip(ENTRY_LIST_COLUMNS, tuple(row))
        }
        for row in rows
    ]
    promotions = promoted_dash_by_field_note_ids(
        conn, (entry["id"] for entry in entries),
    )
    links = correction_links_by_entry_ids(
        conn, (entry["id"] for entry in entries),
    )
    for entry in entries:
        entry["promoted_dash"] = promotions.get(entry["id"])
        _apply_correction_link(entry, links.get(entry["id"]))
    return entries


def count_entry_rows(
    conn,
    unreviewed: bool = False,
    project: Optional[str] = None,
    category_prefix: Optional[str] = None,
) -> int:
    """Matching row count for the same filters as :func:`list_entry_rows`."""
    where, params = _entry_list_filters(
        conn,
        unreviewed=unreviewed,
        project=project,
        category_prefix=category_prefix,
    )
    total = query_scalar(
        conn,
        "SELECT COUNT(*) FROM ouroboros_entries o "
        f"{where}",
        tuple(params),
    )
    return int(total or 0)


def cmd_list_entries(
    conn,
    unreviewed: bool = False,
    project: Optional[str] = None,
    category_prefix: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> str:
    return "\n".join(
        _format_row([row[name] for name in ENTRY_LIST_COLUMNS])
        for row in list_entry_rows(
            conn, unreviewed, project, category_prefix, limit, offset,
        )
    )


def get_entry_row(conn, entry_id: int) -> Optional[dict]:
    """One typed entry by id (full body, plus archived_at), or ``None``."""
    p = _p(conn)
    row = query_one(
        conn,
        "SELECT o.id, o.timestamp, o.agent, COALESCE(o.context,''), "
        "o.category, o.body, COALESCE(o.reviewed_at,''), "
        "COALESCE(p.slug,''), COALESCE(o.archived_at,'') "
        "FROM ouroboros_entries o "
        "LEFT JOIN projects p ON p.id = o.project_id "
        f"WHERE o.id={p}",
        (entry_id,),
    )
    if row is None:
        return None
    names = (*ENTRY_LIST_COLUMNS, "archived_at")
    entry = {
        name: (int(value) if name == "id"
               else "" if value is None else str(value))
        for name, value in zip(names, tuple(row))
    }
    entry["promoted_dash"] = promoted_dash_by_field_note_ids(
        conn, [entry_id],
    ).get(entry_id)
    _apply_correction_link(
        entry, correction_links_by_entry_ids(conn, [entry_id]).get(entry_id),
    )
    return entry


def cmd_mark_reviewed(conn, entry_id: int) -> str:
    p = _p(conn)
    exists = query_scalar(
        conn, f"SELECT COUNT(*) FROM ouroboros_entries WHERE id={p}", (entry_id,)
    )
    if not exists:
        raise LookupError(f"entry {entry_id} not found")

    ts = iso8601_now()
    conn.execute(
        f"UPDATE ouroboros_entries SET reviewed_at={p} WHERE id={p}",
        (ts, entry_id),
    )
    conn.commit()
    return f"Marked entry {entry_id} as reviewed at {ts}"


def cmd_mark_archived(
    conn,
    entry_id: Optional[int] = None,
    all_reviewed: bool = False,
    project: Optional[str] = None,
) -> str:
    p = _p(conn)
    ts = iso8601_now()
    if all_reviewed:
        where = "reviewed_at IS NOT NULL AND archived_at IS NULL"
        params: list[object] = []
        if project:
            where += f" AND project_id={p}"
            params.append(resolve_project_id(conn, project))
        count = query_scalar(
            conn,
            f"SELECT COUNT(*) FROM ouroboros_entries WHERE {where}",
            tuple(params),
        )
        if not count:
            return "0"
        conn.execute(
            f"UPDATE ouroboros_entries SET archived_at={p} WHERE {where}",
            (ts, *params),
        )
        conn.commit()
        return str(count)

    if entry_id is None:
        raise ValueError("entry ID required")
    exists = query_scalar(
        conn, f"SELECT COUNT(*) FROM ouroboros_entries WHERE id={p}", (entry_id,)
    )
    if not exists:
        raise LookupError(f"entry {entry_id} not found")
    conn.execute(
        f"UPDATE ouroboros_entries SET archived_at={p} WHERE id={p}",
        (ts, entry_id),
    )
    conn.commit()
    return "1"
