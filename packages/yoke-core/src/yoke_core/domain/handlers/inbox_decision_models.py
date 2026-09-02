"""Typed payloads and responses for decision requests and the Inbox."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from yoke_core.domain.machine_approval_requests import (
    MachineApprovalLifecycleStatus,
)


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
    def exclude_lifecycle_gate_requests(cls, value: str) -> str:
        if value == "lifecycle_transition_approval":
            raise ValueError(
                "lifecycle approvals are created only by the lifecycle gate"
            )
        return value


class DecisionMutationResponse(BaseModel):
    request: Dict[str, Any]
    created: Optional[bool] = None


class MachineApprovalLifecycleRequest(BaseModel):
    authorization_id: UUID
    state: MachineApprovalLifecycleStatus
    occurred_at: datetime
    expires_at: Optional[datetime] = None
    reason: Optional[str] = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def require_state_evidence(self):
        timestamps = (self.occurred_at, self.expires_at)
        if any(value is not None and value.utcoffset() is None for value in timestamps):
            raise ValueError("machine authorization timestamps require a timezone")
        if self.state == "pending" and self.expires_at is None:
            raise ValueError("pending machine authorization requires expires_at")
        if self.state == "withdrawn" and not self.reason:
            raise ValueError("withdrawn machine authorization requires a reason")
        return self


class MachineApprovalLifecycleResponse(BaseModel):
    request: Optional[Dict[str, Any]] = None
    created: bool
    applied: bool


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
    "MachineApprovalLifecycleRequest",
    "MachineApprovalLifecycleResponse",
]
