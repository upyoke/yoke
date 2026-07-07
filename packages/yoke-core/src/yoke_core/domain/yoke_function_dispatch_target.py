"""Server-side target item-ref resolution for the function dispatcher.

The relay contract (CLI grammar contract) requires that no `yoke` CLI
adapter touch the DB before dispatch: a client carries the raw public
item reference (``PREFIX-N`` or a bare project-local number) on
``target.item_ref`` plus whatever project context it knows client-side
on ``target.project_id``, and the dispatcher resolves the internal
``items.id`` here — identically for in-process and HTTPS callers.

Resolution ladder for bare numeric refs:

1. ``target.project_id`` — explicit client context (``--project`` flag,
   ``YOKE_PROJECT``, or the machine checkout->project map).
2. The calling session's current/recent item's project
   (``harness_sessions`` keyed on the bound ``actor.session_id``).
3. No context -> the parser's loud bare-ref usage error.

``PREFIX-N`` refs resolve through the unique public-prefix ladder in
:func:`yoke_core.domain.yok_n_parser.parse_item_id` regardless of
context.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)


def _session_project_context(
    conn: Any, session_id: str
) -> Optional[int]:
    """Infer project context from the session's current/recent item."""
    if not session_id:
        return None
    from yoke_core.domain import db_backend

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            "SELECT current_item_id, recent_item_id FROM harness_sessions "
            f"WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
    except db_backend.database_error_types():
        return None
    if row is None:
        return None
    candidates = (
        row["current_item_id"] if hasattr(row, "keys") else row[0],
        row["recent_item_id"] if hasattr(row, "keys") else row[1],
    )
    for raw in candidates:
        if raw is None or str(raw).strip() == "":
            continue
        try:
            item_id = int(str(raw).strip())
        except ValueError:
            continue
        item_row = conn.execute(
            f"SELECT project_id FROM items WHERE id = {p}",
            (item_id,),
        ).fetchone()
        if item_row is None:
            continue
        value = (
            item_row["project_id"] if hasattr(item_row, "keys") else item_row[0]
        )
        if value is not None:
            return int(value)
    return None


def resolve_target_item_ref(
    request: FunctionCallRequest,
) -> Optional[FunctionCallResponse]:
    """Resolve ``target.item_ref`` into ``target.item_id`` in place.

    Returns ``None`` on success / no-op; a typed error response when the
    ref cannot be resolved. An explicit ``target.item_id`` wins — the
    ref is only consulted when the id is absent.
    """
    target = request.target
    if target.item_ref is None or target.item_id is not None:
        return None
    from yoke_core.domain import db_helpers
    from yoke_core.domain.yok_n_parser import parse_item_id

    try:
        with db_helpers.connect() as conn:
            context: Optional[Union[str, int]] = target.project_id or None
            if context is None:
                context = _session_project_context(
                    conn, request.actor.session_id
                )
            target.item_id = parse_item_id(
                target.item_ref,
                project=context,
                conn=conn,
                allow_bare_internal=False,
            )
            # The client-side context hint has served its purpose; clear
            # it so permission scoping derives from the resolved item's
            # own project, not the caller's ambient checkout (a PREFIX-N
            # ref may legitimately point at another project).
            target.project_id = None
    except ValueError as exc:
        return FunctionCallResponse(
            success=False,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            error=FunctionError(
                code="item_ref_unresolved",
                message=f"target.item_ref {target.item_ref!r}: {exc}",
                jsonpath="$.target.item_ref",
            ),
        )
    return None


__all__ = ["resolve_target_item_ref"]
