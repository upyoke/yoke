"""Compact, cursor-paged Ouroboros roster reads for the browser list.

The operator ``ouroboros.entry.list`` surface still returns full rows with
offset paging. The browser roster opts into ``shape=roster`` so it can page
by the selected field with a bounded evidence preview instead of full evidence bodies.
"""

from __future__ import annotations

import base64
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.ouroboros_entry_presentation import entry_wire_value
from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.field_note_dash_promotion import (
    promoted_dash_by_field_note_ids,
)
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.ouroboros_entries import (
    DEFAULT_ENTRY_LIST_LIMIT,
    MAX_ENTRY_LIST_LIMIT,
)
from yoke_core.domain.ouroboros_entry_corrections import (
    correction_links_by_entry_ids,
)
from yoke_core.domain.project_identity import resolve_project_id

from yoke_core.domain.ouroboros_roster_order import (
    ROSTER_PREVIEW_LENGTH,
    SORT_COLUMNS,
    normalize_sort,
    continuation,
    encode_continuation,
)

REVIEW_STATES = ("all", "unreviewed", "reviewed")
ROSTER_SHAPE = "roster"
COMPACT_ENTRY_FIELDS = (
    "id",
    "timestamp",
    "agent",
    "context",
    "category",
    "reviewed_at",
    "project",
    "preview",
)
RELOAD_FIRST_PAGE = "Reload the Ouroboros page to restart paging from the newest match."


class RosterCursorError(ValueError):
    """A paging cursor could not be read. The message names the recovery."""


class RosterFilterError(ValueError):
    """A roster criterion was not one of the named values."""

    def __init__(self, message: str, jsonpath: str) -> None:
        super().__init__(message)
        self.jsonpath = jsonpath


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def encode_cursor(entry_id: int) -> str:
    raw = dumps_compact({"id": int(entry_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = loads_text(
            base64.urlsafe_b64decode((cursor + padding).encode()).decode(),
        )
        entry_id = payload["id"]  # type: ignore[index]
        if set(payload) != {"id"}:  # type: ignore[arg-type]
            raise ValueError
        return int(entry_id)
    except Exception as exc:
        raise RosterCursorError(
            f"cursor {cursor!r} is malformed. {RELOAD_FIRST_PAGE}"
        ) from exc


def _review_clause(review_state: str) -> str:
    if review_state == "unreviewed":
        return "o.reviewed_at IS NULL AND o.archived_at IS NULL"
    if review_state == "reviewed":
        return "o.reviewed_at IS NOT NULL"
    return ""


def _roster_filters(
    conn: Any,
    *,
    project: str,
    project_ids: Optional[list[int]],
    review_state: str,
    category_prefix: Optional[str],
    after_id: Optional[int],
) -> tuple[str, list[object]]:
    p = _p(conn)
    ids = (
        project_ids if project_ids is not None else [resolve_project_id(conn, project)]
    )
    conditions = [f"o.project_id IN ({','.join([p] * len(ids))})" if ids else "1=0"]
    params: list[object] = list(ids)
    review_sql = _review_clause(review_state)
    if review_sql:
        conditions.append(review_sql)
    if category_prefix:
        conditions.append(f"o.category LIKE {p}")
        params.append(f"{category_prefix}%")
    if after_id is not None:
        conditions.append(f"o.id < {p}")
        params.append(after_id)
    return f"WHERE {' AND '.join(conditions)}", params


def _bounded_limit(limit: Optional[int]) -> int:
    if limit is None:
        return DEFAULT_ENTRY_LIST_LIMIT
    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > MAX_ENTRY_LIST_LIMIT:
        raise ValueError(f"limit must be <= {MAX_ENTRY_LIST_LIMIT}")
    return limit


def parse_review_state(raw: object, *, unreviewed: bool) -> str:
    if raw is None or raw == "":
        return "unreviewed" if unreviewed else "all"
    state = str(raw)
    if state not in REVIEW_STATES:
        raise RosterFilterError(
            "review_state must be all, unreviewed, or reviewed. " + RELOAD_FIRST_PAGE,
            "$.payload.review_state",
        )
    if unreviewed and state != "unreviewed":
        raise RosterFilterError(
            "unreviewed=true conflicts with review_state="
            f"{state!r}. {RELOAD_FIRST_PAGE}",
            "$.payload.review_state",
        )
    return state


def parse_category_prefix(raw: object) -> Optional[str]:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise RosterFilterError(
            "category_prefix must be a string. " + RELOAD_FIRST_PAGE,
            "$.payload.category_prefix",
        )
    return raw


def parse_roster_shape(raw: object) -> bool:
    if raw is None or raw == "":
        return False
    if raw != ROSTER_SHAPE:
        raise RosterFilterError(
            f"shape must be omitted or {ROSTER_SHAPE!r}. {RELOAD_FIRST_PAGE}",
            "$.payload.shape",
        )
    return True


def _compact_rows(conn: Any, rows: list) -> list[dict[str, Any]]:
    entries = [
        {
            name: entry_wire_value(name, value)
            for name, value in zip(COMPACT_ENTRY_FIELDS, tuple(row))
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
        preview = entry["preview"]
        entry["preview"] = " ".join(preview[:ROSTER_PREVIEW_LENGTH].split())
        if len(preview) > ROSTER_PREVIEW_LENGTH:
            entry["preview"] += "…"
        promo = promotions.get(entry["id"])
        entry["promoted_dash"] = (
            None
            if promo is None
            else {
                "item_id": promo["item_id"],
                "public_ref": promo["public_ref"],
                "project_id": promo["project_id"],
                "project": promo["project"],
            }
        )
        link = links.get(entry["id"]) or {}
        entry["corrects"] = link.get("corrects")
        entry["superseded_by"] = link.get("superseded_by")
    return entries


def list_roster_page(
    conn: Any,
    *,
    project: str = "",
    project_ids: Optional[list[int]] = None,
    sort: Optional[dict] = None,
    review_state: str = "all",
    category_prefix: Optional[str] = None,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
) -> dict[str, Any]:
    """Newest-first keyset page plus the matching count behind it.

    A project or explicit project-id set is required: missing scope never falls
    back to an unscoped query. The count ignores the cursor so it names
    every row the criteria match, not the page already loaded.
    """
    if not project and project_ids is None:
        raise RosterFilterError(
            "project is required for the roster list; unknown or "
            f"omitted projects never fall back to an unscoped query. "
            f"{RELOAD_FIRST_PAGE}",
            "$.payload.project",
        )
    if review_state not in REVIEW_STATES:
        raise RosterFilterError(
            "review_state must be all, unreviewed, or reviewed. " + RELOAD_FIRST_PAGE,
            "$.payload.review_state",
        )
    try:
        ordering = normalize_sort(sort)
    except ValueError as exc:
        raise RosterFilterError(str(exc), "$.payload.sort") from exc
    ids = (
        project_ids if project_ids is not None else [resolve_project_id(conn, project)]
    )
    try:
        cursor_where, cursor_params = continuation(cursor, ordering, ids, conn=conn)
    except ValueError as exc:
        raise RosterCursorError(str(exc)) from exc
    bound = _bounded_limit(limit)
    p = _p(conn)
    where, params = _roster_filters(
        conn,
        project=project,
        project_ids=ids,
        review_state=review_state,
        category_prefix=category_prefix,
        after_id=None,
    )
    matching_count = int(
        query_scalar(
            conn,
            "SELECT COUNT(*) FROM ouroboros_entries o " + where,
            tuple(params),
        )
        or 0
    )
    page_where, page_params = _roster_filters(
        conn,
        project=project,
        project_ids=ids,
        review_state=review_state,
        category_prefix=category_prefix,
        after_id=None,
    )
    if cursor_where:
        page_where += " AND " + cursor_where.format(p=p)
        page_params.extend(cursor_params)
    page_params.append(bound)
    expression = SORT_COLUMNS[ordering["column"]]
    direction = ordering["direction"].upper()
    nulls = "FIRST" if direction == "ASC" else "LAST"
    rows = query_rows(
        conn,
        "SELECT o.id, o.timestamp, o.agent, COALESCE(o.context,''), "
        "o.category, o.reviewed_at, COALESCE(p.slug,''), "
        f"SUBSTR(COALESCE(o.body,''),1,{p}), {expression} "
        "FROM ouroboros_entries o "
        "LEFT JOIN projects p ON p.id = o.project_id "
        f"{page_where} ORDER BY {expression} {direction} NULLS {nulls}, o.id {direction} LIMIT {p}",
        (ROSTER_PREVIEW_LENGTH + 1, *page_params),
    )
    entries = _compact_rows(conn, rows)
    next_cursor = None
    if len(entries) == bound:
        last = {**entries[-1], "_sort_value": tuple(rows[-1])[-1]}
        next_cursor = encode_continuation(last, ordering, ids)
    return {
        "entries": entries,
        "matching_count": matching_count,
        "next_cursor": next_cursor,
        "limit": bound,
    }


__all__ = [
    "COMPACT_ENTRY_FIELDS",
    "REVIEW_STATES",
    "ROSTER_SHAPE",
    "RosterCursorError",
    "RosterFilterError",
    "decode_cursor",
    "encode_cursor",
    "list_roster_page",
    "parse_category_prefix",
    "parse_review_state",
    "parse_roster_shape",
]
