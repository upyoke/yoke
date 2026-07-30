"""Internal server-side prefetch for the resync Stage-2 comparison.

The resync comparison stage opened a local ``connect()`` for its item +
epic-task prefetch, which fails over an https control plane (no local
Postgres). This handler relays that prefetch server-side (dispatched
in-process against a local Postgres connection, or over https
server-side) while the engine keeps every GitHub REST call local.

The handler runs the engine's inline prefetch — every item's rendered
body, actor labels, and the merge-implied flag
(:meth:`yoke_core.domain.workflow_runtime.WorkflowRuntime.stage_implies_merge`
resolved server-side so the engine consumes a plain bool rather than a
live runtime object), plus every epic-task's compared fields. The engine
keeps all field-comparison logic. It is ``adapter_status='internal'``
(engine glue, never an agent CLI surface), so it carries no CLI adapter
row, and read-only, so no authorization product scope is required.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ComparePrefetchRequest(BaseModel):
    pass


class ComparePrefetchResponse(BaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    epic_tasks: List[Dict[str, Any]] = Field(default_factory=list)


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _row_to_dict(row: Any) -> dict:
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _render_actor_token(conn: Any, value: str) -> str:
    """Render an ``items.source`` / ``items.owner`` value to a label token.

    Wraps :func:`yoke_core.domain.actors.actor_label_or_passthrough` so a
    missing-actor or missing-label condition does not abort the entire
    detect pass — the raw column value falls through so the comparator
    still names a value the operator can investigate.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.actors import ActorError, actor_label_or_passthrough

    try:
        return actor_label_or_passthrough(conn, value)
    except ActorError:
        return value or ""
    except db_backend.operational_error_types(conn):
        try:
            conn.rollback()
        except Exception:
            pass
        return value or ""


def _prefetch_items(conn: Any) -> List[Dict[str, Any]]:
    from yoke_core.domain.render_body import build_body
    from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

    items: List[Dict[str, Any]] = []
    try:
        cur = conn.execute(
            "SELECT id, title, status, priority, workflow_id, source, owner, "
            "frozen, blocked FROM items"
        )
        for row in cur.fetchall():
            d = _row_to_dict(row)
            item_id = row["id"]
            runtime = load_item_workflow_runtime(conn, int(item_id))
            status = str(d.get("status") or "")
            items.append(
                {
                    "id": item_id,
                    "title": d.get("title"),
                    "status": d.get("status"),
                    "priority": d.get("priority"),
                    "workflow_id": d.get("workflow_id"),
                    "frozen": d.get("frozen"),
                    "blocked": d.get("blocked"),
                    "body": build_body(conn, item_id) or "",
                    "source_label": _render_actor_token(conn, d.get("source") or ""),
                    "owner_label": _render_actor_token(conn, d.get("owner") or ""),
                    "implies_merge": bool(runtime.stage_implies_merge(status)),
                }
            )
    except Exception:  # noqa: BLE001 - partial prefetch preserved, as inline
        pass
    return items


def _prefetch_epic_tasks(conn: Any) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    try:
        cur = conn.execute(
            "SELECT epic_id, task_num, title, status, COALESCE(body, '') as body "
            "FROM epic_tasks"
        )
        for row in cur.fetchall():
            tasks.append(
                {
                    "epic_id": row["epic_id"],
                    "task_num": row["task_num"],
                    "title": row["title"],
                    "status": row["status"],
                    "body": row["body"],
                }
            )
    except Exception:  # noqa: BLE001 - partial prefetch preserved, as inline
        pass
    return tasks


def handle_compare_prefetch(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the Stage-2 item + epic-task prefetch.

    Runs the engine's inline prefetch. The per-prefetch ``except`` matches
    the inline behavior — a partial read keeps the rows gathered so far.
    """
    try:
        with _connect_rw() as conn:
            items = _prefetch_items(conn)
            epic_tasks = _prefetch_epic_tasks(conn)
    except Exception as exc:  # noqa: BLE001 - surfaced so the engine aborts
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="compare_prefetch_failed", message=str(exc)
            ),
        )

    return HandlerOutcome(
        result_payload={"items": items, "epic_tasks": epic_tasks},
        primary_success=True,
    )


__all__ = [
    "ComparePrefetchRequest",
    "ComparePrefetchResponse",
    "handle_compare_prefetch",
]
