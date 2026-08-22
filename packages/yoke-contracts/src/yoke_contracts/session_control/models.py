"""Wire models shared by session-control functions and adapters."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS


MessageState = Literal["pending", "injected", "acknowledged", "expired", "cancelled"]
LaunchState = Literal[
    "queued",
    "assigned",
    "launching",
    "awaiting_registration",
    "succeeded",
    "failed",
    "cancelled",
    "expired",
    "outcome_unknown",
]


class RecipientSelector(BaseModel):
    session_ids: List[str] = Field(default_factory=list)
    item_refs: List[str] = Field(default_factory=list)
    epic_tasks: List[str] = Field(default_factory=list)
    process_keys: List[str] = Field(default_factory=list)
    projects: List[str] = Field(default_factory=list)
    universe: bool = False
    executor_families: List[str] = Field(default_factory=list)
    executor_surfaces: List[str] = Field(default_factory=list)
    work_roles: List[str] = Field(default_factory=list)
    execution_lanes: List[str] = Field(default_factory=list)
    worktree_lanes: List[str] = Field(default_factory=list)
    machine_ids: List[str] = Field(default_factory=list)
    liveness: List[str] = Field(default_factory=list)
    exclude_session_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _known_surfaces(self) -> "RecipientSelector":
        unknown = sorted(set(self.executor_surfaces) - set(KNOWN_SURFACE_LABELS))
        if unknown:
            raise ValueError(f"unknown executor surfaces: {', '.join(unknown)}")
        if not any(
            (
                self.session_ids,
                self.item_refs,
                self.epic_tasks,
                self.process_keys,
                self.projects,
                self.universe,
            )
        ):
            raise ValueError("at least one recipient anchor is required")
        return self


class MessagePreviewRequest(BaseModel):
    selector: RecipientSelector


class MessageRecipient(BaseModel):
    session_id: str
    project: str
    executor: str
    executor_surface: Optional[str] = None
    machine_id: Optional[str] = None
    liveness: str
    messageability: Dict[str, Any] = Field(default_factory=dict)
    resolution: List[str] = Field(default_factory=list)


class MessagePreviewResponse(BaseModel):
    recipients: List[MessageRecipient]
    recipient_count: int
    confirmation_token: Optional[str] = None


class MessageSendRequest(BaseModel):
    selector: RecipientSelector
    body: str
    idempotency_key: Optional[str] = None
    confirmation_token: Optional[str] = None


class MessageSendResponse(BaseModel):
    message_id: str
    recipients: List[MessageRecipient]
    recipient_count: int
    deduplicated: bool = False


class MessageListRequest(BaseModel):
    state: Optional[MessageState] = None
    session_id: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)


class MessageGetRequest(BaseModel):
    message_id: str


class MessageAcknowledgeRequest(BaseModel):
    message_id: str


class MessageCancelRequest(BaseModel):
    message_id: str


class MessageLeaseRequest(BaseModel):
    session_id: str
    hook_event: str
    limit: int = Field(default=10, ge=1, le=50)


class MessageLeaseCompleteRequest(BaseModel):
    lease_id: str
    injected: bool
    result: str


class LaunchPreviewRequest(BaseModel):
    project: str
    executor_surface: str
    machine_id: Optional[str] = None
    model: Optional[str] = None
    allow_surface_fallback: bool = False


class LaunchCreateRequest(LaunchPreviewRequest):
    instructions: str
    idempotency_key: str
    presentation: Optional[str] = None


class LaunchMutationRequest(BaseModel):
    launch_id: str


class LaunchReconcileRequest(LaunchMutationRequest):
    observed_native_id: Optional[str] = None


class RelayPollRequest(BaseModel):
    relay_id: str
    machine_id: str
    projects: List[str]
    surfaces: Dict[str, str]


class RelayClaimRequest(BaseModel):
    relay_id: str
    job_kind: Literal["wake", "launch"]
    job_id: str


class RelayReportRequest(RelayClaimRequest):
    result: str
    native_id: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "LaunchCreateRequest",
    "LaunchMutationRequest",
    "LaunchPreviewRequest",
    "LaunchReconcileRequest",
    "LaunchState",
    "MessageAcknowledgeRequest",
    "MessageCancelRequest",
    "MessageGetRequest",
    "MessageLeaseCompleteRequest",
    "MessageLeaseRequest",
    "MessageListRequest",
    "MessagePreviewRequest",
    "MessagePreviewResponse",
    "MessageRecipient",
    "MessageSendRequest",
    "MessageSendResponse",
    "MessageState",
    "RecipientSelector",
    "RelayClaimRequest",
    "RelayPollRequest",
    "RelayReportRequest",
]
