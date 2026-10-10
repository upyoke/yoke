"""Compact Items-roster query: server-side filters, match count, cursor paging.

The Items page stays searchable across the whole durable item history without
transferring it, so every filter the page offers is evaluated here — before
the page is selected — and the caller receives one page plus the total number
of matches standing behind it.

Ordering, cursor comparison and tie-breaking use the same allowlisted
expression. Native update instants fall back to creation only when null.
The cursor encodes the exact instant as canonical UTC and binds it natively
when continued; text sort keys remain opaque. ``i.id`` makes the order total
so equal instants still page deterministically.

This module is layer ``domain_invariants``: it receives project ids the
caller has already resolved and authorized, and imports nothing from the
handlers package.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.work_claim_targets import scope_int_sql


from yoke_core.domain.item_roster_order import (
    ROSTER_SORT_EXPRESSION,
    RosterCursorError,
    decode_cursor,
    encode_cursor,
    sort_expression,
)

_ROSTER_COLUMNS = (
    "i.id AS internal_id",
    "i.title",
    "i.workflow_id",
    "i.workflow_version_id",
    "i.status",
    "i.updated_at",
    "i.created_at",
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _search_clause(conn: Any, search: str) -> tuple[str, list[Any]]:
    """Match the four concepts the roster's text box has always searched.

    Public reference and title read the item row. Owner and active claim
    holder read the same label projections their rendered cells read, as
    ``EXISTS`` subqueries rather than joins — a join on claims would multiply
    a row per claim and make both the count and the page dishonest.
    """
    p = _p(conn)
    pattern = f"%{search.strip().lower()}%"
    ref_expression = "LOWER(r.public_ref)"
    arms = [f"{ref_expression} LIKE {p}", f"LOWER(i.title) LIKE {p}"]
    params: list[Any] = [pattern, pattern]
    if _table_exists(conn, "actors"):
        arms.append(
            "EXISTS (SELECT 1 FROM actors ol "
            "WHERE CAST(ol.id AS TEXT) = i.owner "
            f"AND LOWER(ol.name) LIKE {p})"
        )
        params.append(pattern)
    if _table_exists(conn, "work_claims"):
        claim_item_id = scope_int_sql(conn, "wc.scope", "item_id")
        arms.append(
            "EXISTS (SELECT 1 FROM work_claims wc "
            "LEFT JOIN harness_sessions hs ON hs.session_id = wc.session_id "
            "LEFT JOIN actors a ON a.id = hs.actor_id "
            "WHERE wc.target_kind = 'item' AND wc.released_at IS NULL "
            f"AND {claim_item_id} = i.id AND ("
            f"LOWER(a.name) LIKE {p} "
            f"OR LOWER(a.system_component) LIKE {p} "
            f"OR LOWER(hs.executor) LIKE {p} "
            f"OR LOWER(wc.session_id) LIKE {p}))"
        )
        params.extend([pattern, pattern, pattern, pattern])
    return "(" + " OR ".join(arms) + ")", params


def _filter_sql(
    conn: Any,
    *,
    project_ids: Optional[Sequence[int]],
    search: Optional[str],
    workflow: Optional[str],
    status: Optional[str],
) -> tuple[str, list[Any]]:
    """Compose the shared predicate the count and the page both read."""
    p = _p(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if project_ids is not None:
        ordered = sorted({int(project_id) for project_id in project_ids})
        markers = ", ".join(p for _ in ordered)
        clauses.append(f"i.project_id IN ({markers})")
        params.extend(ordered)
    if workflow:
        clauses.append(f"i.workflow_id = {p}")
        params.append(workflow)
    if status:
        clauses.append(f"i.status = {p}")
        params.append(status)
    if search and search.strip():
        clause, search_params = _search_clause(conn, search)
        clauses.append(clause)
        params.extend(search_params)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def _filter_choices(
    conn: Any,
    where: str,
    params: Sequence[Any],
) -> dict[str, Any]:
    """Every workflow and status present in the scope, not just on this page.

    Deliberately computed over the project scope alone rather than over the
    workflow/status criteria themselves: choosing one workflow must not erase
    the other choices from the control that offered them.
    """
    from yoke_core.domain.workflow_runtime import workflow_runtime_from_row

    rows = _dict_rows(
        conn.execute(
            "SELECT DISTINCT i.workflow_id, i.status, i.workflow_version_id "
            f"FROM items i JOIN projects p ON p.id = i.project_id JOIN item_refs r ON r.item_id = i.id{where}",
            tuple(params),
        )
    )
    if not rows:
        return {"workflow_ids": [], "statuses": []}
    version_ids = sorted({int(row["workflow_version_id"]) for row in rows})
    markers = ", ".join(_p(conn) for _ in version_ids)
    runtimes = {
        int(version["workflow_version_id"]): workflow_runtime_from_row(version)
        for version in _dict_rows(
            conn.execute(
                "SELECT v.id AS workflow_version_id, v.workflow_id, v.version, "
                "v.definition_json, v.definition_digest FROM workflow_versions v "
                f"WHERE v.id IN ({markers})",
                tuple(version_ids),
            )
        )
    }
    labels: dict[str, str] = {}
    for row in rows:
        status = str(row["status"])
        runtime = runtimes.get(int(row["workflow_version_id"]))
        label = runtime.stage_label(status) if runtime is not None else status
        labels.setdefault(status, str(label or status))
    return {
        "workflow_ids": sorted({str(row["workflow_id"]) for row in rows}),
        "statuses": [
            {"id": status, "label": labels[status]}
            for status in sorted(labels, key=lambda key: labels[key].lower())
        ],
    }


def read_item_roster(
    conn: Any,
    *,
    project_ids: Optional[Iterable[int]] = None,
    search: Optional[str] = None,
    workflow: Optional[str] = None,
    status: Optional[str] = None,
    page_size: int,
    cursor: Optional[str] = None,
    sort_column: str = "updated_at",
    sort_direction: str = "desc",
) -> dict[str, Any]:
    """Read one roster page plus the full match count behind it.

    ``project_ids`` is the already-resolved, already-authorized scope: an
    empty collection means the caller may see no project and answers empty,
    while ``None`` means unrestricted.

    Filter choices are computed only for a first page. Continuing an existing
    paging sequence means the caller already holds them, and they describe a
    scope the cursor did not change — recomputing a scope-wide DISTINCT on
    every ``Load more`` would buy the same answer again.
    """
    expression = sort_expression(conn, sort_column, sort_direction)
    order = sort_direction.upper()
    comparison = ">" if sort_direction == "asc" else "<"
    scope = None if project_ids is None else list(project_ids)
    if scope is not None and not scope:
        return {
            "rows": [],
            "match_count": 0,
            "next_cursor": None,
            "filters": {"workflow_ids": [], "statuses": []},
        }
    p = _p(conn)
    where, params = _filter_sql(
        conn,
        project_ids=scope,
        search=search,
        workflow=workflow,
        status=status,
    )
    # Choices are offered for the project scope alone. Narrowing them by the
    # very criteria they select would delete the option a reader needs to
    # switch back to.
    filters = None
    if not cursor:
        scope_where, scope_params = _filter_sql(
            conn,
            project_ids=scope,
            search=None,
            workflow=None,
            status=None,
        )
        filters = _filter_choices(conn, scope_where, scope_params)
    source = f"FROM items i JOIN projects p ON p.id = i.project_id JOIN item_refs r ON r.item_id = i.id{where}"
    match_count = int(
        conn.execute(
            f"SELECT COUNT(*) {source}",
            tuple(params),
        ).fetchone()[0]
    )

    page_where, page_params = where, list(params)
    if cursor:
        sort_value, cursor_id = decode_cursor(cursor, sort_column, sort_direction)
        if sort_column == "updated_at":
            sort_value = instant_parameter(conn, sort_value)
        joiner = " AND " if page_where else " WHERE "
        page_where = (
            page_where
            + joiner
            + (
                f"({expression} {comparison} {p} OR "
                f"({expression} = {p} AND i.id {comparison} {p}))"
            )
        )
        page_params.extend([sort_value, sort_value, cursor_id])
    # One row beyond the page proves whether another page exists without a
    # second count against the cursor predicate.
    rows = _dict_rows(
        conn.execute(
            f"SELECT {', '.join(_ROSTER_COLUMNS)}, "
            f"{expression} AS roster_sort_value "
            f"FROM items i JOIN projects p ON p.id = i.project_id JOIN item_refs r ON r.item_id = i.id{page_where} "
            f"ORDER BY {expression} {order}, i.id {order} LIMIT {p}",
            (*page_params, page_size + 1),
        )
    )
    has_more = len(rows) > page_size
    page = rows[:page_size]
    next_cursor = (
        encode_cursor(
            page[-1]["roster_sort_value"],
            int(page[-1]["internal_id"]),
            sort_column,
            sort_direction,
        )
        if has_more and page
        else None
    )
    for row in page:
        row.pop("roster_sort_value", None)
    return {
        "rows": page,
        "match_count": match_count,
        "next_cursor": next_cursor,
        "filters": filters,
    }


__all__ = [
    "ROSTER_SORT_EXPRESSION",
    "RosterCursorError",
    "decode_cursor",
    "encode_cursor",
    "read_item_roster",
]
