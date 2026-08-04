"""Function handlers for active item-owned worktree lanes."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from yoke_contracts.item_worktrees import EVIDENCE_ONLY_RECOVERY_REASON
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.item_worktrees import LANE_ROLES
from yoke_core.domain.workflow_behavior import (
    LANE_IMPLEMENTATION,
    worktree_lane_policy,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)


_RECOVERY_STATUS = "implemented"


class ItemWorktreeLane(BaseModel):
    id: int
    item_id: int
    branch: str
    path: Optional[str] = None
    commit_sha: Optional[str] = None
    lane_role: str
    state: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    released_at: Optional[str] = None


class ItemWorktreesGetRequest(BaseModel):
    lane_role: str = "implementation"


class ItemWorktreesGetResponse(BaseModel):
    item_id: int
    worktree: Optional[ItemWorktreeLane] = None


class CleanLaneAttestation(BaseModel):
    worktree_id: int
    branch: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    observed_clean: bool = False
    #: How the caller established the lane holds no unpreserved work — a
    #: git-verified clean checkout, or a landed branch whose lane directory
    #: the merge already removed. See
    #: :mod:`yoke_core.domain.item_worktree_lane_release_evidence`.
    evidence: str = ""


class ItemWorktreesReleaseRequest(BaseModel):
    all_active: bool = False
    reason: str = Field(..., min_length=1)
    clean_lane_attestation: Optional[CleanLaneAttestation] = None


class ItemWorktreesReleaseResponse(BaseModel):
    item_id: int
    released_count: int
    released_worktree_ids: list[int]
    reason: str


class ItemWorktreesReleaseMergedLaneRequest(BaseModel):
    branch: str = Field(..., min_length=1)


class ItemWorktreesReleaseMergedLaneResponse(BaseModel):
    item_id: int
    branch: str
    released_count: int


def _error(code: str, message: str, *, jsonpath: str | None = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _item_id(request: FunctionCallRequest) -> int | None:
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return None
    return int(target.item_id)


def handle_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the active lane for one item and lane role."""
    item_id = _item_id(request)
    if item_id is None:
        return _error(
            "target_invalid",
            "item_worktrees.get requires target.kind='item' with item_id",
        )
    try:
        payload = ItemWorktreesGetRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", f"get payload invalid: {exc}")
    if payload.lane_role not in LANE_ROLES:
        return _error(
            "payload_invalid",
            f"unknown item worktree lane role {payload.lane_role!r}",
            jsonpath="$.payload.lane_role",
        )

    from yoke_core.domain import db_helpers
    from yoke_core.domain.item_worktrees import primary_item_worktree

    with db_helpers.connect() as conn:
        lane = primary_item_worktree(
            conn,
            item_id,
            lane_role=payload.lane_role,
        )
    response = ItemWorktreesGetResponse(
        item_id=item_id,
        worktree=ItemWorktreeLane.model_validate(lane) if lane else None,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


def handle_release(request: FunctionCallRequest) -> HandlerOutcome:
    """Release one attested clean evidence-only implementation lane."""
    item_id = _item_id(request)
    if item_id is None:
        return _error(
            "target_invalid",
            "item_worktrees.release requires target.kind='item' with item_id",
        )
    try:
        payload = ItemWorktreesReleaseRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", f"release payload invalid: {exc}")
    if not payload.all_active:
        return _error(
            "payload_invalid",
            "release requires all_active=true; partial lane release is not "
            "a public recovery operation",
            jsonpath="$.payload.all_active",
        )
    if payload.reason != EVIDENCE_ONLY_RECOVERY_REASON:
        return _error(
            "payload_invalid",
            "item worktree release is restricted to evidence-only recovery",
            jsonpath="$.payload.reason",
        )

    from yoke_core.domain import db_backend, db_helpers
    from yoke_core.domain.item_worktrees import (
        list_item_worktrees,
        release_item_worktrees,
    )

    with db_helpers.connect() as conn:
        lock_item_workflow_bindings(conn, (item_id,))
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        item = conn.execute(
            f"SELECT status FROM items WHERE id = {marker}",
            (item_id,),
        ).fetchone()
        if item is None:
            return _error("not_found", f"item {item_id} was not found")
        status = str(item["status"] if hasattr(item, "keys") else item[0])
        if status != _RECOVERY_STATUS:
            return _error(
                "recovery_status_invalid",
                "evidence-only lane release requires item status "
                f"{_RECOVERY_STATUS!r}; got {status!r}",
            )
        policy = worktree_lane_policy(load_item_workflow_runtime(conn, item_id))
        if policy.allowed_roles != frozenset({LANE_IMPLEMENTATION}):
            return _error(
                "recovery_lane_policy_invalid",
                "evidence-only lane release requires a single implementation "
                "lane workflow policy",
            )
        active = list_item_worktrees(conn, item_id, active_only=True)
        if not active:
            response = ItemWorktreesReleaseResponse(
                item_id=item_id,
                released_count=0,
                released_worktree_ids=[],
                reason=payload.reason,
            )
            return HandlerOutcome(
                result_payload=response.model_dump(),
                primary_success=True,
            )
        if len(active) != 1 or active[0]["lane_role"] != LANE_IMPLEMENTATION:
            return _error(
                "recovery_lane_set_invalid",
                "evidence-only recovery requires exactly one active "
                "implementation lane",
            )
        lane = active[0]
        attestation = payload.clean_lane_attestation
        if attestation is None or not attestation.observed_clean:
            return _error(
                "clean_lane_attestation_required",
                "release requires a fresh clean-lane attestation",
                jsonpath="$.payload.clean_lane_attestation",
            )
        expected = (
            int(lane["id"]),
            str(lane["branch"]),
            str(lane["path"] or ""),
        )
        attested = (
            attestation.worktree_id,
            attestation.branch,
            attestation.path,
        )
        if attested != expected:
            return _error(
                "clean_lane_attestation_stale",
                "the attested lane no longer matches the active lane",
                jsonpath="$.payload.clean_lane_attestation",
            )
        released_count = release_item_worktrees(
            conn,
            item_id=item_id,
            branch=str(lane["branch"]),
        )
    response = ItemWorktreesReleaseResponse(
        item_id=item_id,
        released_count=released_count,
        released_worktree_ids=[int(row["id"]) for row in active],
        reason=payload.reason,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


def handle_release_merged_lane(request: FunctionCallRequest) -> HandlerOutcome:
    """Retire the lane row for a branch whose worktree the merge removed.

    The merge engine deletes the lane directory once the branch is proven
    contained by the target. Leaving the row ``active`` afterwards points
    every reader at a path that no longer exists — and one of those readers
    is the verification tree-binding guard, which then refuses the done-gate
    run that is the only thing that would have released the row. Releasing
    here keeps the directory and the row retired by the same act, so that
    cycle cannot form.

    Idempotent: a retry after the row is already released reports zero.
    """
    item_id = _item_id(request)
    if item_id is None:
        return _error(
            "target_invalid",
            "item_worktrees.release_merged_lane requires target.kind='item' "
            "with item_id",
        )
    try:
        payload = ItemWorktreesReleaseMergedLaneRequest.model_validate(
            request.payload or {}
        )
    except Exception as exc:
        return _error(
            "payload_invalid", f"release_merged_lane payload invalid: {exc}"
        )

    from yoke_core.domain import db_helpers
    from yoke_core.domain.item_worktrees import release_item_worktrees

    with db_helpers.connect() as conn:
        lock_item_workflow_bindings(conn, (item_id,))
        released_count = release_item_worktrees(
            conn,
            item_id=item_id,
            branch=payload.branch,
        )
    response = ItemWorktreesReleaseMergedLaneResponse(
        item_id=item_id,
        branch=payload.branch,
        released_count=released_count,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


__all__ = [
    "ItemWorktreeLane",
    "ItemWorktreesGetRequest",
    "ItemWorktreesGetResponse",
    "CleanLaneAttestation",
    "ItemWorktreesReleaseMergedLaneRequest",
    "ItemWorktreesReleaseMergedLaneResponse",
    "ItemWorktreesReleaseRequest",
    "ItemWorktreesReleaseResponse",
    "handle_get",
    "handle_release",
    "handle_release_merged_lane",
]
