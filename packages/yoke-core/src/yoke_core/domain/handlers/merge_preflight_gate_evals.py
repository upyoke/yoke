"""Internal server-side reads for the merge-worktree preparation gates.

The merge-worktree preflight runs three control-plane reads that used to
open a local ``connect()`` (or shell out to a child process that opened one):

* the epic-task completeness gate (which epic tasks are not in a terminal
  success status),
* the integration dependency gate (unsatisfied blocking dependencies at the
  ``integration`` gate point), and
* the ``items.blocked`` refusal gate (resolve the active worktree lane for a
  branch, then read the item's blocked flag).

Over an https control plane there is no local Postgres, so those reads
failed. These handlers relay the reads server-side (dispatched in-process
against a local Postgres connection, or over https server-side) while the
merge engine keeps all git and filesystem work local.

Each handler is a thin wrapper over unchanged domain state — the epic_tasks
survey query, :func:`yoke_core.domain.dependency_planning.evaluate_item_gate`,
and :func:`yoke_core.domain.advance_blocked_gate.evaluate`. The terminal
success statuses and every block narrative stay client-side in
:mod:`yoke_core.engines.merge_worktree_prepare_preflight`; these handlers
return only the raw verdict data. They are ``adapter_status='internal'``
(pure preflight glue, never an agent CLI surface), so they carry no CLI
adapter inventory row.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class EpicTaskStatusesRequest(BaseModel):
    epic_id: Optional[int] = None


class EpicTaskStatusesResponse(BaseModel):
    tasks: List[Dict[str, Any]] = Field(default_factory=list)


class DependencyGateRequest(BaseModel):
    item_ref: str = Field(..., min_length=1)
    gate_point: str = "integration"


class DependencyGateResponse(BaseModel):
    is_blocked: bool
    unsatisfied_blockers: List[Dict[str, Any]] = Field(default_factory=list)


class BlockedGateRequest(BaseModel):
    branch: str = Field(..., min_length=1)


class BlockedGateResponse(BaseModel):
    applicable: bool
    item_id: Optional[int] = None
    item_ref: Optional[str] = None
    blocked: bool = False
    reason: Optional[str] = None


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


def _resolved_epic_id(request: FunctionCallRequest, payload_epic_id: object) -> int:
    if payload_epic_id is not None:
        return int(payload_epic_id)
    if request.target.item_id is not None:
        return int(request.target.item_id)
    raise ValueError("resolved epic target required")


def handle_epic_task_statuses(request: FunctionCallRequest) -> HandlerOutcome:
    """Return every epic task's ``task_num`` + ``status`` in task-num order.

    The completeness verdict (which statuses count as terminal, and whether
    any incomplete tasks block the merge) stays in the engine so the terminal
    success set has a single owner; this read reports raw task state only.
    """
    try:
        body = EpicTaskStatusesRequest.model_validate(request.payload)
        epic_id = _resolved_epic_id(request, body.epic_id)
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"epic_task_statuses payload invalid: {exc}")

    try:
        with _connect_rw() as conn:
            p = _placeholder(conn)
            rows = conn.execute(
                "SELECT task_num, status FROM epic_tasks "
                f"WHERE epic_id = {p} ORDER BY task_num",
                (epic_id,),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - degrade to an error the caller can skip
        return _err("epic_task_read_failed", str(exc))

    tasks = [{"task_num": row[0], "status": row[1]} for row in rows]
    return HandlerOutcome(
        result_payload={"tasks": tasks},
        primary_success=True,
    )


def handle_dependency_gate(request: FunctionCallRequest) -> HandlerOutcome:
    """Evaluate the integration dependency gate for one item reference.

    Wraps :func:`yoke_core.domain.dependency_planning.evaluate_item_gate`
    unchanged and returns its blocked flag + per-blocker detail dicts. The
    reference is normalized to the ``YOK-N`` text form the dependency edges
    store, matching the retired ``evaluate-gate`` CLI path exactly.
    """
    try:
        body = DependencyGateRequest.model_validate(request.payload)
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"dependency_gate payload invalid: {exc}")

    item_ref = body.item_ref if body.item_ref.startswith("YOK-") else f"YOK-{body.item_ref}"

    from yoke_core.domain.dependency_planning import evaluate_item_gate

    try:
        with _connect_rw() as conn:
            result = evaluate_item_gate(conn, item_ref, body.gate_point)
    except Exception as exc:  # noqa: BLE001 - degrade to an error the caller can skip
        return _err("dependency_gate_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "is_blocked": bool(result.is_blocked),
            "unsatisfied_blockers": [b.to_dict() for b in result.unsatisfied_blockers],
        },
        primary_success=True,
    )


def handle_blocked_gate(request: FunctionCallRequest) -> HandlerOutcome:
    """Resolve the active worktree lane for a branch, then read the blocked flag.

    ``applicable`` is False when no active ``item_worktrees`` lane owns the
    branch (the gate does nothing in that case, matching the engine). When a
    lane exists the item's blocked verdict comes from the unchanged
    :func:`yoke_core.domain.advance_blocked_gate.evaluate`. The public
    ``item_ref`` is rendered server-side (while the connection is live) so the
    engine's block narrative reads the same project-prefixed reference over
    https as it does on a local connection.
    """
    try:
        body = BlockedGateRequest.model_validate(request.payload)
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"blocked_gate payload invalid: {exc}")

    from yoke_core.domain.advance_blocked_gate import evaluate as _eval_blocked
    from yoke_core.domain.project_identity import render_item_ref

    try:
        with _connect_rw() as conn:
            p = _placeholder(conn)
            row = conn.execute(
                "SELECT item_id FROM item_worktrees "
                f"WHERE branch = {p} AND state = 'active'",
                (body.branch,),
            ).fetchone()
            if row is None:
                return HandlerOutcome(
                    result_payload={"applicable": False},
                    primary_success=True,
                )
            item_id = int(row[0])
            decision = _eval_blocked(conn, item_id)
            item_ref = render_item_ref(conn, item_id)
    except Exception as exc:  # noqa: BLE001 - degrade to an error the caller can skip
        return _err("blocked_gate_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "applicable": True,
            "item_id": item_id,
            "item_ref": item_ref,
            "blocked": bool(decision.blocked),
            "reason": decision.reason,
        },
        primary_success=True,
    )


__all__ = [
    "BlockedGateRequest",
    "BlockedGateResponse",
    "DependencyGateRequest",
    "DependencyGateResponse",
    "EpicTaskStatusesRequest",
    "EpicTaskStatusesResponse",
    "handle_blocked_gate",
    "handle_dependency_gate",
    "handle_epic_task_statuses",
]
