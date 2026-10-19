"""Typed payloads and responses for decision requests and the Inbox."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class InboxListRequest(BaseModel):
    project_ids: Optional[List[int]] = None
    include_read: bool = False


class InboxListResponse(BaseModel):
    needs_decision: List[Dict[str, Any]]
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    pending_actor_message_count: int = 0


class DecisionRoleAuthority(BaseModel):
    scope_kind: str
    scope_id: int
    role_name: str


class DecisionCreateRequest(BaseModel):
    kind: str
    subject_type: str
    subject_key: str
    project_id: Optional[int] = None
    org_id: Optional[int] = None
    originator_actor_id: Optional[int] = None
    role_authorities: List[DecisionRoleAuthority] = Field(default_factory=list)
    named_actor_ids: List[int] = Field(default_factory=list)
    subject_context: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def exclude_gate_owned_requests(cls, value: str) -> str:
        gate_owned = {
            "lifecycle_transition_approval": "the lifecycle gate",
            "merge_candidate_review": (
                "the merge boundary's candidate-review gate "
                "(`yoke merge-review candidate evaluate`)"
            ),
        }
        owner = gate_owned.get(value)
        if owner is not None:
            raise ValueError(f"{value} requests are created only by {owner}")
        return value


class DecisionMutationResponse(BaseModel):
    request: Dict[str, Any]
    created: Optional[bool] = None


class DecisionResolveRequest(BaseModel):
    request_id: int
    action: str
    note: Optional[str] = None


class DecisionWithdrawRequest(BaseModel):
    request_id: int
    reason: str


class DecisionDisposeEndedRequest(BaseModel):
    project_ids: Optional[List[int]] = None


class DecisionDisposeEndedResponse(BaseModel):
    reaped_executions: List[Dict[str, Any]]
    withdrawn: List[Dict[str, Any]]
    withdrawn_count: int
    retained_count: int


__all__ = [
    "DecisionCreateRequest",
    "DecisionDisposeEndedRequest",
    "DecisionDisposeEndedResponse",
    "DecisionMutationResponse",
    "DecisionResolveRequest",
    "DecisionRoleAuthority",
    "DecisionWithdrawRequest",
    "InboxListRequest",
    "InboxListResponse",
]
