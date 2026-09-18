"""Project-wide lane inventory: every registered lane with its owner's state.

Lane hygiene is decided by a runtime that holds the *checkout* — only it can
read a worktree's residue, its git registration, and whether a branch still
exists. The facts that decide whether a lane may go are control-plane rows:
which item owns the lane, whether that item is terminal, what the project's
target branch is. Those two runtimes are not the same machine whenever a
project relays to a control plane over https, which is every hosted and
external project.

This read is the bridge. It answers "what does the control plane know about
this project's lanes" in one call, so a checkout-holding client can run lane
hygiene over any transport instead of needing local SQL. It is deliberately
project-scoped rather than item-scoped: the caller is enumerating lanes it
found on disk and does not yet know which items own them.

Released lanes are included. A lane released in the registry but still on
disk is exactly the residue a caller is looking for, so filtering to active
rows would hide the cases this exists to find.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ItemWorktreeInventoryRequest(BaseModel):
    project: str = Field(..., min_length=1)


class InventoryLane(BaseModel):
    """One registered lane, joined to the facts a cleanup decision needs."""

    item_id: int
    public_ref: str
    status: str
    branch: str
    path: str | None = None
    state: str
    target_branch: str


class ItemWorktreeInventoryResponse(BaseModel):
    project: str
    lanes: list[InventoryLane]


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath="$.payload"),
    )


def _rows(conn: Any, project_id: int) -> list[dict[str, Any]]:
    from yoke_core.domain.db_backend import connection_is_postgres
    from yoke_core.domain.db_helpers import query_rows

    marker = "%s" if connection_is_postgres(conn) else "?"
    return query_rows(
        conn,
        "SELECT iw.item_id, iw.branch, iw.path, iw.state, i.status, "
        "COALESCE(p.default_branch, 'main') AS target_branch "
        "FROM item_worktrees iw "
        "JOIN items i ON i.id = iw.item_id "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE i.project_id = {marker} "
        "ORDER BY iw.item_id, iw.branch",
        (project_id,),
    )


def handle_inventory(request: FunctionCallRequest) -> HandlerOutcome:
    """Return every registered lane in *project* with its owning item's state.

    Read-only and side-effect free. An unknown project is a structured
    refusal naming the project rather than an empty inventory, because a
    caller that silently reads zero lanes would conclude the machine has no
    lanes to retire and quietly skip the work.
    """
    try:
        payload = ItemWorktreeInventoryRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _error("payload_invalid", f"inventory payload invalid: {exc}")

    from yoke_core.domain import db_helpers
    from yoke_core.domain.item_ref_render import render_item_refs
    from yoke_core.domain.project_identity import (
        AmbiguousProjectRefError,
        resolve_project_id,
    )

    with db_helpers.connect() as conn:
        try:
            project_id = resolve_project_id(conn, payload.project)
        except AmbiguousProjectRefError as exc:
            return _error("project_ambiguous", str(exc))
        except LookupError as exc:
            return _error("project_not_found", str(exc))
        rows = _rows(conn, int(project_id))
        refs = render_item_refs(conn, [int(row["item_id"]) for row in rows])

    lanes = [
        InventoryLane(
            item_id=int(row["item_id"]),
            public_ref=refs.get(int(row["item_id"]), ""),
            status=str(row["status"]),
            branch=str(row["branch"]),
            path=str(row["path"]) if row["path"] else None,
            state=str(row["state"]),
            target_branch=str(row["target_branch"]),
        )
        for row in rows
    ]
    response = ItemWorktreeInventoryResponse(
        project=payload.project,
        lanes=lanes,
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


__all__ = [
    "InventoryLane",
    "ItemWorktreeInventoryRequest",
    "ItemWorktreeInventoryResponse",
    "handle_inventory",
]
