"""Item search handler: ``items.search.run``.

Matches items two ways from one query. The keyword arm greps the authored
text — title, spec, design spec, technical plan. The reference arm reads the
query as an item reference and matches ``items.project_sequence``, so a
number finds its item whether or not that number appears anywhere in the
item's prose.

The read is uncapped unless the caller passes a ``limit``; a surface that
renders a short result list should pass its own cap so a broad keyword does
not ship the whole backlog. Carries ``claim_required_kind=None`` (a read).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.item_ref import format_item_ref, parse_public_item_ref
from yoke_core.domain.handlers.items_project_scope import (
    actor_visible_scope,
    ambiguous_project_error,
    resolve_visible_project_id,
)


class ItemsSearchRequest(BaseModel):
    keywords: str
    project: Optional[str] = None
    limit: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000,
        description=(
            "Cap on returned matches, newest first. Omit for every match — "
            "callers that render a short result list should pass their cap "
            "so a broad keyword does not ship the whole backlog."
        ),
    )


class ItemsSearchResponse(BaseModel):
    matches: List[Dict[str, Any]]


def handle_items_search(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    keywords = payload.get("keywords")
    if not keywords or not str(keywords).strip():
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="keywords is required and must be non-empty",
                jsonpath="$.payload.keywords",
            ),
        )

    limit = payload.get("limit")
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = -1
        if limit < 1 or limit > 1000:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message="limit out of bounds (1..1000)",
                    jsonpath="$.payload.limit",
                ),
            )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import AmbiguousProjectRefError

    conn = connect()
    try:
        scoped = actor_visible_scope(conn, request)
        explicit_project = payload.get("project") or None
        if scoped is not None and not scoped:
            matches = []
        else:
            try:
                project_id = resolve_visible_project_id(
                    conn, explicit_project, scoped,
                )
            except AmbiguousProjectRefError as exc:
                return ambiguous_project_error(str(exc), "$.payload.project")
            if explicit_project is not None and project_id is None:
                matches = []
            else:
                matches = _search_items(
                    conn,
                    str(keywords),
                    project_id=project_id,
                    visible_project_ids=scoped,
                    limit=limit,
                )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"matches": matches},
        primary_success=True,
    )


def _search_items(
    conn: Any,
    keywords: str,
    *,
    project_id: Optional[int],
    visible_project_ids: Optional[set[int]],
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Match items by keyword across their authored text, and — when the query
    reads as an item reference — by that reference.

    A reference matches on ``project_sequence`` (qualified by the project's
    public prefix when the query carries one), so a query naming an item by
    number finds it whether or not the number appears in any of its prose.
    Reference matches sort ahead of keyword matches; the rest are newest
    first, so a capped result list holds the most recent work rather than the
    oldest.
    """
    if visible_project_ids is not None and not visible_project_ids:
        return []
    pattern = f"%{keywords.lower()}%"
    match_clauses = [
        "(LOWER(i.title) LIKE %s OR LOWER(i.spec) LIKE %s "
        "OR LOWER(i.design_spec) LIKE %s OR LOWER(i.technical_plan) LIKE %s)"
    ]
    params: list[Any] = [pattern, pattern, pattern, pattern]
    ref_prefix, ref_sequence = parse_public_item_ref(keywords)
    if ref_sequence is not None:
        ref_clause = "i.project_sequence = %s"
        params.append(ref_sequence)
        if ref_prefix is not None:
            ref_clause += " AND UPPER(p.public_item_prefix) = %s"
            params.append(ref_prefix)
        match_clauses.append(f"({ref_clause})")
    where = "WHERE (" + " OR ".join(match_clauses) + ")"
    if project_id is not None:
        where += " AND i.project_id = %s"
        params.append(int(project_id))
    if visible_project_ids is not None:
        ordered_ids = sorted(visible_project_ids)
        markers = ", ".join("%s" for _ in ordered_ids)
        where += f" AND i.project_id IN ({markers})"
        params.extend(ordered_ids)
    order = "ORDER BY i.id DESC"
    if ref_sequence is not None:
        order = (
            "ORDER BY CASE WHEN i.project_sequence = %s THEN 0 ELSE 1 END, "
            "i.id DESC"
        )
        params.append(ref_sequence)
    sql = (
        "SELECT i.id, i.title, i.status, i.project_sequence, "
        "p.id AS project_id, p.slug AS project, p.public_item_prefix "
        f"FROM items i JOIN projects p ON p.id = i.project_id {where} {order}"
    )
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "id": int(row["id"]),
            "public_ref": format_item_ref(
                row["project"],
                row["public_item_prefix"],
                int(row["project_sequence"]),
            ),
            "title": row["title"],
            "status": row["status"],
            "project": row["project"],
            "project_id": int(row["project_id"]),
        }
        for row in rows
    ]


__all__ = [
    "ItemsSearchRequest",
    "ItemsSearchResponse",
    "handle_items_search",
]
