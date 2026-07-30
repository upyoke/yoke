"""Internal server-side reads/writes for the merge-worktree finalize path.

Two merge-engine control-plane touches used to open a local ``connect()``
inside the engine, which fails over an https control plane (no local
Postgres):

* the fail-closed prune authority verdict (does a DB-owned terminal
  worktree / branch still hold active authority, or is it safe to prune?),
  and
* the post-rebase QA requirement resolution (materialize the item's
  release-transition QA plan, then find the pre-merge-verification command
  requirement to execute).

These handlers relay both touches server-side (dispatched in-process
against a local Postgres connection, or over https server-side) while the
merge engine keeps every git and filesystem operation — worktree removal,
branch deletion, test execution — local.

Each handler is a thin wrapper over unchanged domain state: the prune
verdict wraps the unchanged
:func:`yoke_core.engines.merge_worktree_safe_prune._terminal_owner` /
:func:`~yoke_core.engines.merge_worktree_safe_prune._has_active_authority`
fail-closed logic, and the post-rebase read wraps
:func:`yoke_core.domain.qa_plan_attachments.materialize_for_item` plus the
unchanged pre-merge-verification command-case query. The prune/keep
decision and every engine-side narrative stay client-side; these handlers
return only the raw verdict data. They are ``adapter_status='internal'``
(merge glue, never an agent CLI surface), so they carry no CLI adapter
inventory row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class PruneAuthorityRequest(BaseModel):
    branch: str = Field(..., min_length=1)
    path: Optional[str] = None


class PruneAuthorityResponse(BaseModel):
    prunable: bool
    reason: str


class PostRebaseRequirementRequest(BaseModel):
    transition_id: str = Field(default="release", min_length=1)


class PostRebaseRequirementResponse(BaseModel):
    requirement_id: Optional[int] = None


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def handle_prune_authority_verdict(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the fail-closed prune verdict for a branch / worktree identity.

    ``prunable`` is True only when a unique terminal DB owner exists AND no
    active authority holds it — exactly the two-gate decision the engine
    computed inline. ``reason`` is ``no_terminal_owner`` (keep silently),
    ``active_authority`` (keep with a "Preserving actively claimed"
    narrative in loop-one), or ``prunable``. The terminal-success set and
    every git check (clean / merged / removal) stay engine-owned; this read
    reports only the DB authority verdict.
    """
    try:
        body = PruneAuthorityRequest.model_validate(request.payload)
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"prune authority payload invalid: {exc}")

    from yoke_core.engines.merge_worktree_safe_prune import (
        _has_active_authority,
        _terminal_owner,
    )

    path = Path(body.path) if body.path else None
    try:
        with _connect_rw() as conn:
            owner = _terminal_owner(conn, branch=body.branch, path=path)
            if owner is None:
                verdict = {"prunable": False, "reason": "no_terminal_owner"}
            elif _has_active_authority(conn, owner, path):
                verdict = {"prunable": False, "reason": "active_authority"}
            else:
                verdict = {"prunable": True, "reason": "prunable"}
    except Exception as exc:  # noqa: BLE001 - connect failure == authority unavailable
        return _err("prune_authority_read_failed", str(exc))

    return HandlerOutcome(result_payload=verdict, primary_success=True)


def handle_post_rebase_requirement(request: FunctionCallRequest) -> HandlerOutcome:
    """Materialize the item's release QA plan, return its command requirement.

    Wraps the unchanged single-connection sequence the engine ran inline:
    :func:`yoke_core.domain.qa_plan_attachments.materialize_for_item` at the
    supplied transition, then the pre-merge-verification command-case query.
    Returns ``requirement_id=None`` when no such requirement exists (the
    no-attached-plan case); a materialization failure surfaces as a
    structured error so the engine can propagate it exactly as before.
    """
    item_id = request.target.item_id
    if item_id is None:
        return _err("target_invalid", "post_rebase_requirement requires target.item_id")
    try:
        body = PostRebaseRequirementRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"post_rebase payload invalid: {exc}")

    from yoke_core.domain import db_backend
    from yoke_core.domain.qa_plan_attachments import materialize_for_item

    try:
        with _connect_rw() as conn:
            materialize_for_item(
                conn,
                item_id=int(item_id),
                transition_id=body.transition_id,
            )
            marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                "SELECT q.id FROM qa_requirements q "
                "JOIN qa_plans p ON p.id=q.plan_id "
                "JOIN qa_plan_cases c "
                "ON c.plan_id=q.plan_id AND c.case_key=q.plan_case_key "
                f"WHERE q.item_id={marker} "
                f"AND q.workflow_transition_id={marker} "
                "AND q.waived_at IS NULL "
                "AND p.slug='pre-merge-verification' "
                "AND c.method_id='command' "
                "ORDER BY q.id DESC LIMIT 1",
                (int(item_id), body.transition_id),
            ).fetchone()
            requirement_id = int(row[0]) if row is not None else None
    except Exception as exc:  # noqa: BLE001 - materialize failure blocks the merge
        return _err("post_rebase_requirement_failed", str(exc))

    return HandlerOutcome(
        result_payload={"requirement_id": requirement_id},
        primary_success=True,
    )


__all__ = [
    "PostRebaseRequirementRequest",
    "PostRebaseRequirementResponse",
    "PruneAuthorityRequest",
    "PruneAuthorityResponse",
    "handle_post_rebase_requirement",
    "handle_prune_authority_verdict",
]
