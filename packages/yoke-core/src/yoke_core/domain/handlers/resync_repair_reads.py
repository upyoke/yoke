"""Internal server-side reads for the resync repair path.

The resync repair helpers opened a local ``connect()`` for three
control-plane reads, which fails over an https control plane (no local
Postgres): the item-by-reference lookup that resolves the public-ref
title prefix (also the runtime item-status probe), the epic-task repair
context (parent id + public ref + the task's title/status), and the
epic-task body the compact-mirror budget guard renders into a new GitHub
issue.

These handlers relay those reads server-side (dispatched in-process
against a local Postgres connection, or over https server-side) while the
repair helpers keep every GitHub REST call local. Each handler is a thin
wrapper over the same query the helper ran inline. They are
``adapter_status='internal'`` (engine glue, never an agent CLI surface),
so they carry no CLI adapter row, and read-only, so no authorization
product scope is required.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ItemLookupRequest(BaseModel):
    ref: str = Field(..., min_length=1)


class ItemLookupResponse(BaseModel):
    found: bool
    id: Optional[int] = None
    ref: str = ""
    status: Optional[str] = None


class EpicTaskRepairReadRequest(BaseModel):
    epic_ref: str = Field(..., min_length=1)
    task_num: int


class EpicTaskRepairReadResponse(BaseModel):
    parent_ref: str = ""
    task_found: bool
    title: str = ""
    status: str = ""


class EpicTaskBodyRequest(BaseModel):
    epic_ref: str = Field(..., min_length=1)
    task_num: int


class EpicTaskBodyResponse(BaseModel):
    body: str


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def handle_item_lookup(request: FunctionCallRequest) -> HandlerOutcome:
    """Look up an item by its public ref (or the engine's own id token).

    The reference is a ``PREFIX-N`` ref or the internal id the resync engine
    carries; anything else (a slug fragment) names no item. Returns the id,
    the item's rendered public ref, and its status. Rendering the
    ref here keeps ref composition on the side that can read the project's
    prefix and the item's project sequence, so no caller reconstructs a
    public ref from the internal id. A missing row is a valid
    ``found=False`` answer; the caller decides whether that is an empty
    title prefix or a ``None`` status probe.
    """
    from yoke_core.domain.item_ref_resolution import internal_item_key
    from yoke_core.domain.project_identity import render_item_ref

    try:
        body = ItemLookupRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"item_lookup payload invalid: {exc}")

    try:
        with _connect_rw() as conn:
            p = _placeholder(conn)
            item_id = internal_item_key(conn, body.ref)
            row = (
                conn.execute(
                    f"SELECT id, status FROM items WHERE id = {p}",
                    (item_id,),
                ).fetchone()
                if item_id is not None
                else None
            )
            public_ref = render_item_ref(conn, int(row[0])) if row else ""
    except Exception as exc:  # noqa: BLE001 - surfaced so the caller aborts
        return _err("item_lookup_failed", str(exc))

    if row is None:
        return HandlerOutcome(
            result_payload={
                "found": False,
                "id": None,
                "ref": "",
                "status": None,
            },
            primary_success=True,
        )
    return HandlerOutcome(
        result_payload={
            "found": True,
            "id": row[0],
            "ref": public_ref,
            "status": row[1],
        },
        primary_success=True,
    )


def handle_epic_task_repair_read(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the parent id/public ref + the epic task's title/status.

    Runs two reads on one connection: the parent item id (from its public
    ref or the engine's id token) and the ``epic_tasks`` title/status row. The
    parent's public ref is rendered here, where the project's prefix and
    the item's project sequence are readable, so the caller never composes
    a ref from the internal id. A missing task row yields
    ``task_found=False``; the caller aborts the repair with the same "row
    not found" error.
    """
    from yoke_core.domain.item_ref_resolution import internal_item_key
    from yoke_core.domain.project_identity import render_item_ref

    try:
        body = EpicTaskRepairReadRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"epic_task_repair_read invalid: {exc}")

    try:
        with _connect_rw() as conn:
            p = _placeholder(conn)
            epic_id = internal_item_key(conn, body.epic_ref)
            parent_row = (
                conn.execute(
                    f"SELECT id FROM items WHERE id = {p}",
                    (epic_id,),
                ).fetchone()
                if epic_id is not None
                else None
            )
            task_row = (
                conn.execute(
                    "SELECT title, status FROM epic_tasks "
                    f"WHERE epic_id = {p} AND task_num = {p}",
                    # Untyped text binds against either epic_tasks.epic_id column type.
                    (str(epic_id), body.task_num),
                ).fetchone()
                if epic_id is not None
                else None
            )
            # render_item_ref tolerates schemas without project tables and
            # falls back to the default-prefix + internal-id form.
            parent_ref = render_item_ref(conn, int(parent_row[0])) if parent_row else ""
    except Exception as exc:  # noqa: BLE001 - surfaced so the caller aborts
        return _err("epic_task_repair_read_failed", str(exc))

    if task_row is None:
        return HandlerOutcome(
            result_payload={
                "parent_ref": parent_ref,
                "task_found": False,
                "title": "",
                "status": "",
            },
            primary_success=True,
        )
    return HandlerOutcome(
        result_payload={
            "parent_ref": parent_ref,
            "task_found": True,
            "title": task_row[0] or "",
            "status": task_row[1] or "",
        },
        primary_success=True,
    )


def handle_epic_task_body(request: FunctionCallRequest) -> HandlerOutcome:
    """Return an epic task's raw body for compact-mirror rendering.

    Wraps :func:`yoke_core.domain.epic_resolution.task_get_body` unchanged.
    The engine swallowed any read failure to an empty body; here that
    surfaces as a structured error so the caller degrades to ``""`` exactly
    as its inline ``except`` clause did.
    """
    try:
        body = EpicTaskBodyRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"epic_task_body payload invalid: {exc}")

    from yoke_core.domain.epic_resolution import task_get_body
    from yoke_core.domain.item_ref_resolution import internal_item_key

    try:
        with _connect_rw() as conn:
            epic_id = internal_item_key(conn, body.epic_ref)
            if epic_id is None:
                raise LookupError(f"epic {body.epic_ref!r} not found")
            text = task_get_body(conn, str(epic_id), int(body.task_num)) or ""
    except Exception as exc:  # noqa: BLE001 - surfaced so the caller degrades to ""
        return _err("epic_task_body_failed", str(exc))

    return HandlerOutcome(result_payload={"body": text}, primary_success=True)


__all__ = [
    "EpicTaskBodyRequest",
    "EpicTaskBodyResponse",
    "EpicTaskRepairReadRequest",
    "EpicTaskRepairReadResponse",
    "ItemLookupRequest",
    "ItemLookupResponse",
    "handle_epic_task_body",
    "handle_epic_task_repair_read",
    "handle_item_lookup",
]
