"""Typed payloads and responses for decision requests and notifications."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class InboxListRequest(BaseModel):
    project_ids: Optional[List[int]] = None
    include_read: bool = False


class InboxListResponse(BaseModel):
    needs_decision: List[Dict[str, Any]]
    requests: List[Dict[str, Any]]
    notifications: List[Dict[str, Any]]


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


class NotificationReadRequest(BaseModel):
    notification_id: int


class NotificationsReadAllRequest(BaseModel):
    project_ids: Optional[List[int]] = None


class NotificationReadResponse(BaseModel):
    read: bool
    notification_id: Optional[int] = None
    count: Optional[int] = None


__all__ = [
    "DecisionCreateRequest",
    "DecisionMutationResponse",
    "DecisionResolveRequest",
    "DecisionRoleAuthority",
    "DecisionWithdrawRequest",
    "InboxListRequest",
    "InboxListResponse",
    "NotificationReadRequest",
    "NotificationReadResponse",
    "NotificationsReadAllRequest",
]
