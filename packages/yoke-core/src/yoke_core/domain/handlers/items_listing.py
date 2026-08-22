"""Items roster handler: ``items.list.run``.

Reuses the filter building blocks of the ``db_router items list``
operator-debug CLI (:class:`yoke_core.domain.queries.ItemFilter` +
``build_where_clause``). Keyword and reference matching is a different
read — see :mod:`yoke_core.domain.handlers.items_search`.

The projection is operator-facing and never emits an internal
``items.id`` or a raw actor id: the ``id`` column renders the item's
public ``PREFIX-N`` ref, ``source`` / ``owner`` render actor display
labels, and the numeric primary key is reachable only through the
explicit ``internal_id`` field for programmatic consumers.

Virtual fields (``body``) are rejected — rendering every body server-side
is the wrong shape for a list read; use ``items.get.run`` per item instead.
Carries ``claim_required_kind=None`` (a read).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.handlers.items_project_scope import (
    actor_visible_scope,
    ambiguous_project_error,
    resolve_visible_project_id,
)
from yoke_core.domain.items_projection import ACTOR_LABEL_FIELDS, DEFAULT_LIST_FIELDS


class ItemsListRequest(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    workflow: Optional[str] = None
    frozen: Optional[bool] = None
    blocked: Optional[bool] = None
    project: Optional[str] = None
    fields: List[str] = Field(
        default_factory=list,
        description=(
            "Column projection. Empty -> "
            "id,title,status,priority,workflow_id,source. ``id`` carries "
            "the public PREFIX-N ref; ``source``/``owner`` carry actor "
            "display labels; ``internal_id`` opts into the numeric key."
        ),
    )
    limit: Optional[int] = Field(default=None, ge=1, le=1000)


class ItemsListResponse(BaseModel):
    rows: List[Dict[str, Any]]
    count: int


def _validated_list_fields(
    requested: List[str],
) -> tuple[List[str], Optional[HandlerOutcome]]:
    from yoke_core.api.service_client_items_parsing import (
        _QI_ALL_FIELDS,
        _QI_VIRTUAL_FIELDS,
    )

    fields = [str(f).strip() for f in requested if str(f).strip()]
    if not fields:
        return list(DEFAULT_LIST_FIELDS), None
    if len(set(fields)) != len(fields):
        return [], HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=(
                    f"duplicate field {fields!r}: each column may be "
                    "requested once"
                ),
                jsonpath="$.payload.fields",
            ),
        )
    for field in fields:
        if field in _QI_VIRTUAL_FIELDS:
            return [], HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message=(
                        f"virtual field {field!r} is not listable; read it "
                        "per item via items.get.run (yoke items get)"
                    ),
                    jsonpath="$.payload.fields",
                ),
            )
        if field not in _QI_ALL_FIELDS:
            return [], HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message=(
                        f"unknown items column {field!r}. Valid: "
                        + ",".join(sorted(_QI_ALL_FIELDS - _QI_VIRTUAL_FIELDS))
                    ),
                    jsonpath="$.payload.fields",
                ),
            )
    return fields, None


def handle_items_list(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain import queries
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import (
        AmbiguousProjectRefError,
        item_project_join_select,
    )

    payload = request.payload or {}
    explicit_project = payload.get("project") or None
    fields, field_error = _validated_list_fields(
        list(payload.get("fields") or [])
    )
    if field_error is not None:
        return field_error
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

    def _opt_bool(key: str) -> Optional[bool]:
        value = payload.get(key)
        return None if value is None else bool(value)

    filt = queries.ItemFilter(
        status=payload.get("status") or None,
        priority=payload.get("priority") or None,
        workflow=payload.get("workflow") or None,
        frozen=_opt_bool("frozen"),
        blocked=_opt_bool("blocked"),
        project=None,
    )
    where_clause, params = queries.build_where_clause(filt, table_prefix="i.")
    select_cols, needs_project = item_project_join_select(fields)
    join = " JOIN projects p ON p.id = i.project_id" if needs_project else ""

    conn = connect()
    try:
        scoped = actor_visible_scope(conn, request)
        if scoped is not None and not scoped:
            rows = []
            out_rows: List[Dict[str, Any]] = []
        else:
            try:
                project_id = resolve_visible_project_id(
                    conn, explicit_project, scoped,
                )
            except AmbiguousProjectRefError as exc:
                return ambiguous_project_error(str(exc), "$.payload.project")
            if explicit_project is not None and project_id is None:
                rows = []
                out_rows = []
            else:
                if project_id is not None:
                    where_clause, params = _append_project_id(
                        where_clause, params, project_id,
                    )
                where_clause, params = _append_project_visibility(
                    where_clause, params, scoped,
                )
                sql = (
                    f"SELECT {select_cols} FROM items i{join} "
                    f"{where_clause} ORDER BY i.id"
                )
                sql_params: tuple = tuple(params)
                if limit is not None:
                    sql += " LIMIT %s"
                    sql_params = (*sql_params, limit)
                rows = conn.execute(sql, sql_params).fetchall()
                out_rows = _render_rows(conn, fields=fields, rows=rows)
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"rows": out_rows, "count": len(out_rows)},
        primary_success=True,
    )


_UNSET_LABEL_TOKENS = frozenset({"none", "null"})

from yoke_core.domain.actors import ActorLabelAmbiguous, ActorLabelMissing, ActorNotFound  # noqa: E402

#: The degrade policy for actor-label cells: any of these means "cannot
#: render" -> empty cell. One orphan actor must not fail the page.
_ACTOR_ERRORS = (ActorNotFound, ActorLabelMissing, ActorLabelAmbiguous)


def _actor_label_batches(
    conn: Any,
    fields: List[str],
    rows: list[tuple],
) -> dict[int, str]:
    """Resolve every distinct actor id on this page in one query.

    Returns ``{actor_id: label}``; ids that cannot be rendered degrade to
    an empty cell rather than failing the listing.
    """
    positions = [i for i, f in enumerate(fields) if f in ACTOR_LABEL_FIELDS]
    actor_ids: set[int] = set()
    for row in rows:
        for position in positions:
            raw = str(row[position] or "").strip()
            if not raw or raw.lower() in _UNSET_LABEL_TOKENS:
                continue
            try:
                actor_ids.add(int(raw))
            except ValueError:
                continue
    if not actor_ids:
        return {}
    ordered = sorted(actor_ids)
    markers = ", ".join("%s" for _ in ordered)
    by_actor: dict[int, list[Any]] = {}
    missing: set[int] = set(ordered)
    for actor_id, *label_parts in conn.execute(
        "SELECT a.id, al.label FROM actors a "
        "LEFT JOIN actor_labels al ON al.actor_id = a.id "
        f"AND al.surface = 'display' WHERE a.id IN ({markers})",
        tuple(ordered),
    ).fetchall():
        missing.discard(int(actor_id))
        by_actor.setdefault(int(actor_id), []).extend(label_parts)
    resolved: dict[int, str] = {}
    for actor_id in ordered:
        labels = [
            str(label) for label in by_actor.get(actor_id, [])
            if label not in (None, "")
        ]
        if len(labels) == 1:
            resolved[actor_id] = labels[0]
            continue
        if len(labels) > 1:
            resolved[actor_id] = ""  # ambiguous display projection
            continue
        try:
            from yoke_core.domain.actor_display import actor_display_name

            resolved[actor_id] = actor_display_name(conn, actor_id)
        except _ACTOR_ERRORS:
            # Orphan/missing-label actor: degrade the cell, never the page.
            resolved[actor_id] = ""
    return resolved


def _render_rows(
    conn: Any,
    fields: List[str],
    rows: list[tuple],
) -> List[Dict[str, Any]]:
    """Project raw storage rows into operator-facing field maps.

    ``id`` renders the item's public ref (batched through
    :class:`ItemRefLookup`); actor-label fields resolve through one
    batched label query per page; every other field passes as text.
    Runs on the handler's already-open connection — no second connect.
    """
    from yoke_core.domain.item_ref_render import render_item_ref_lookup

    ref_position = fields.index("id") if "id" in fields else None
    internal_ids = (
        [int(row[ref_position]) for row in rows]
        if ref_position is not None else []
    )
    ref_lookup = (
        render_item_ref_lookup(conn, internal_ids)
        if ref_position is not None
        else None
    )
    labels = _actor_label_batches(conn, fields, rows)

    def _render_label(raw: Any) -> str:
        text = str(raw or "").strip()
        if not text or text.lower() in _UNSET_LABEL_TOKENS:
            return ""
        try:
            actor_id = int(text)
        except ValueError:
            return text
        return labels.get(actor_id, "")

    out_rows: List[Dict[str, Any]] = []
    for row in rows:
        rendered: Dict[str, Any] = {}
        for position, field in enumerate(fields):
            value = row[position]
            if position == ref_position:
                rendered[field] = ref_lookup(int(value))
            elif field in ACTOR_LABEL_FIELDS:
                rendered[field] = _render_label(value)
            else:
                rendered[field] = "" if value is None else str(value)
        out_rows.append(rendered)
    return out_rows


def _append_project_visibility(
    where_clause: str,
    params: List[Any],
    visible_project_ids: Optional[set[int]],
) -> tuple[str, List[Any]]:
    if visible_project_ids is None:
        return where_clause, params
    ordered_ids = sorted(visible_project_ids)
    markers = ", ".join("%s" for _ in ordered_ids)
    clause = f"i.project_id IN ({markers})"
    prefix = " AND " if where_clause else "WHERE "
    return where_clause + prefix + clause, [*params, *ordered_ids]


def _append_project_id(
    where_clause: str,
    params: List[Any],
    project_id: int,
) -> tuple[str, List[Any]]:
    prefix = " AND " if where_clause else "WHERE "
    return where_clause + prefix + "i.project_id = %s", [*params, int(project_id)]


__all__ = [
    "ItemsListRequest",
    "ItemsListResponse",
    "handle_items_list",
]
