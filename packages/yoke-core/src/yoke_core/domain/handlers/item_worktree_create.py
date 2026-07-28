"""Registered creation of additional item-owned worktree lanes."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.item_worktrees import (
    ADDITIONAL_ITEM_WORKTREE_LANE_ROLES,
)
from yoke_core.domain.handlers.item_worktrees import ItemWorktreeLane
from yoke_core.domain.item_worktree_lane_creation import (
    ItemWorktreeLaneCreationError,
    create_additional_item_worktree_lane,
    ensure_default_item_worktree_lane,
)
from yoke_core.domain.workflow_item_binding_validation import (
    WorkflowItemBindingError,
)


class ItemWorktreesCreateRequest(BaseModel):
    lane_role: str | None = None
    branch: str | None = Field(default=None, min_length=1)

    @field_validator("lane_role")
    @classmethod
    def _additional_lane_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in ADDITIONAL_ITEM_WORKTREE_LANE_ROLES:
            allowed = ", ".join(ADDITIONAL_ITEM_WORKTREE_LANE_ROLES)
            raise ValueError(f"lane_role must be one of: {allowed}")
        return value

    @model_validator(mode="after")
    def _explicit_lane_pair(self) -> "ItemWorktreesCreateRequest":
        if (self.lane_role is None) != (self.branch is None):
            raise ValueError(
                "lane_role and branch must be provided together, or both "
                "omitted to ensure the policy-required default lane"
            )
        return self


class ItemWorktreesCreateResponse(BaseModel):
    item_id: int
    worktree: ItemWorktreeLane


def _error(
    code: str,
    message: str,
    *,
    jsonpath: str | None = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_create(request: FunctionCallRequest) -> HandlerOutcome:
    """Register one explicit worker or integration branch for an item."""
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return _error(
            "target_invalid",
            "item_worktrees.create requires target.kind='item' with item_id",
        )
    item_id = int(target.item_id)
    try:
        payload = ItemWorktreesCreateRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", f"create payload invalid: {exc}")

    from yoke_core.domain import db_helpers
    from yoke_core.domain.path_claims_gate import (
        PathClaimGateBlocked,
        check_worktree_create_gate,
    )

    try:
        with db_helpers.connect() as conn:
            check_worktree_create_gate(conn, item_id)
            if payload.lane_role is None:
                lane = ensure_default_item_worktree_lane(
                    conn,
                    item_id=item_id,
                )
            else:
                lane = create_additional_item_worktree_lane(
                    conn,
                    item_id=item_id,
                    lane_role=payload.lane_role,
                    branch=str(payload.branch),
                )
    except WorkflowItemBindingError as exc:
        code = "not_found" if "does not exist" in str(exc) else "item_inactive"
        return _error(code, str(exc))
    except ItemWorktreeLaneCreationError as exc:
        return _error("lane_creation_refused", str(exc))
    except PathClaimGateBlocked as exc:
        return _error("path_claim_gate_blocked", str(exc))

    response = ItemWorktreesCreateResponse(
        item_id=item_id,
        worktree=ItemWorktreeLane.model_validate(lane),
    )
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


__all__ = [
    "ItemWorktreesCreateRequest",
    "ItemWorktreesCreateResponse",
    "handle_create",
]
