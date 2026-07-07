"""Core read handlers: items.get, epic_tasks.list.

Sibling modules carry the remaining read families (``reads_misc`` for
path_claims.conflicts.list / doctor.run.run / projects.capability.has;
``events_reads`` for the events.* reads) so each file stays under the
350-line budget.

All function ids registered from these modules carry
``claim_required_kind=None`` (reads do not require an active claim).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_core.domain import db_backend
from yoke_core.domain.items_constants import CANONICAL_COLUMNS, STRUCTURED_FIELDS
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# items.get.run
# ---------------------------------------------------------------------------


# Scalar columns surfaced by the schema packet but not part of
# CANONICAL_COLUMNS (pipe-row layout). Adding them here keeps the packet
# promise honest — every items column the packet teaches is readable via
# items.get without having to round-trip through a raw SELECT.
_ADDITIONAL_SCALAR_GET_FIELDS = frozenset({
    "blocked", "blocked_reason", "owner",
    "resolution", "resolution_ref", "resolution_comment",
    "spec_updated_at", "spec_updated_by",
})

_ALLOWED_GET_FIELDS = (
    frozenset(CANONICAL_COLUMNS) | STRUCTURED_FIELDS | _ADDITIONAL_SCALAR_GET_FIELDS
)


class ItemsGetRequest(BaseModel):
    fields: List[str] = Field(
        default_factory=list,
        description="Optional projection. Empty -> full canonical row.",
    )


class ItemsGetResponse(BaseModel):
    item_id: int
    fields: Dict[str, str]


def handle_items_get(request: FunctionCallRequest) -> HandlerOutcome:
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="items.get requires target.kind='item' with item_id",
            ),
        )
    from yoke_core.domain.items_queries import query_item

    requested = list(request.payload.get("fields") or [])
    section = request.payload.get("section")
    item_id = int(target.item_id)
    if section is not None:
        return _items_get_section(item_id, requested, str(section))
    cols = requested or list(CANONICAL_COLUMNS)
    out: Dict[str, str] = {}
    for col in cols:
        if col not in _ALLOWED_GET_FIELDS:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message=f"unknown items column {col!r}",
                    jsonpath=f"$.payload.fields[{cols.index(col)}]",
                ),
            )
        out[col] = query_item(item_id, col)
    return HandlerOutcome(
        result_payload={"item_id": item_id, "fields": out},
        primary_success=True,
    )


def _items_get_section(
    item_id: int, requested: List[str], section: str
) -> HandlerOutcome:
    """Extract one ``## Heading`` block from a single text/body field.

    Server-side home of the ``yoke items get <ref> <field> --section``
    flow (the old client-side extraction read the DB locally, which the
    https relay cannot). Section absence is advisory, not an error —
    ``section_found=false`` with empty content mirrors the CLI's exit-0
    advisory contract.
    """
    if len(requested) != 1:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="section extraction requires exactly one field",
                jsonpath="$.payload.fields",
            ),
        )
    field = requested[0]
    if field not in _ALLOWED_GET_FIELDS:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=f"unknown items column {field!r}",
                jsonpath="$.payload.fields[0]",
            ),
        )
    from yoke_core.domain.items_queries import query_item
    from yoke_core.domain.render_body_section import extract_section

    text = query_item(item_id, field)
    content = extract_section(text or "", section)
    return HandlerOutcome(
        result_payload={
            "item_id": item_id,
            "field": field,
            "section": section,
            "section_found": content is not None,
            "content": content or "",
        },
        primary_success=True,
    )


# ---------------------------------------------------------------------------
# epic_tasks.list.run
# ---------------------------------------------------------------------------


class EpicTasksListRequest(BaseModel):
    pass


class EpicTasksListResponse(BaseModel):
    epic_id: int
    tasks: List[Dict[str, Any]]


def handle_epic_tasks_list(request: FunctionCallRequest) -> HandlerOutcome:
    epic_id = request.target.epic_id
    if epic_id is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="epic_tasks.list requires target.epic_id",
            ),
        )
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT id, epic_id, task_num, title, status, worktree, dependencies "
            f"FROM epic_tasks WHERE epic_id = {p} ORDER BY task_num ASC",
            (str(epic_id),),
        ).fetchall()
    finally:
        conn.close()
    tasks = [
        {
            "id": int(r[0]),
            "epic_id": int(r[1]),
            "task_num": int(r[2]),
            "title": str(r[3] or ""),
            "status": str(r[4] or ""),
            "worktree": str(r[5] or ""),
            "dependencies": str(r[6] or ""),
        }
        for r in rows
    ]
    return HandlerOutcome(
        result_payload={"epic_id": int(epic_id), "tasks": tasks},
        primary_success=True,
    )


__all__ = [
    "ItemsGetRequest", "ItemsGetResponse", "handle_items_get",
    "EpicTasksListRequest", "EpicTasksListResponse", "handle_epic_tasks_list",
]
