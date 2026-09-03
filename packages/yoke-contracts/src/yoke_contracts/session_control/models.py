"""Wire models shared by session-control functions and adapters."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS
from yoke_contracts.session_control.recipient_selector import RecipientSelector
from yoke_contracts.session_control.states import (
    LaunchState,
    MessageListState,
    MessageState,
)
from yoke_contracts.session_control.relay_models import (
    RelayClaimRequest,
    RelayClaimResponse,
    RelayIdleHost,
    RelayIdleHostsRequest,
    RelayIdleHostsResponse,
    RelayListRequest,
    RelayListResponse,
    RelayLivenessReport,
    RelayLivenessRequest,
    RelayLivenessResponse,
    RelayReclaimedHost,
    RelayReportRequest,
    RelayReportResponse,
)
from yoke_contracts.session_control.sender_surface import SenderSurface


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


class ActorMessageRecipient(BaseModel):
    actor_id: int
    label: Optional[str] = None
    kind: str = "human"
    resolution: List[str] = Field(default_factory=list)


class MessagePreviewResponse(BaseModel):
    recipients: List[MessageRecipient]
    actor_recipients: List[ActorMessageRecipient] = Field(default_factory=list)
    recipient_count: int
    confirmation_token: Optional[str] = None


class MessageSendRequest(BaseModel):
    selector: RecipientSelector
    body: str
    idempotency_key: Optional[str] = None
    confirmation_token: Optional[str] = None
    sender_surface: Optional[SenderSurface] = None


class MessageSendResponse(BaseModel):
    message_id: str
    recipients: List[MessageRecipient]
    actor_recipients: List[ActorMessageRecipient] = Field(default_factory=list)
    recipient_count: int
    deduplicated: bool = False


class MessageListRequest(BaseModel):
    state: Optional[MessageListState] = None
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


class MessageListResponse(BaseModel):
    messages: List[Dict[str, Any]]
    count: int


class MessageGetResponse(BaseModel):
    message: Dict[str, Any]


class MessageMutationResponse(MessageGetResponse):
    pass


class MessageLeaseResponse(BaseModel):
    lease_id: str
    messages: List[Dict[str, Any]]
    remaining_count: int = Field(default=0, ge=0)


class LaunchPreviewRequest(BaseModel):
    project: str
    executor_surface: str
    machine_id: Optional[str] = None
    model: Optional[str] = None
    allow_surface_fallback: bool = False

    @field_validator("executor_surface")
    @classmethod
    def _known_launch_surface(cls, value: str) -> str:
        if value not in KNOWN_SURFACE_LABELS:
            raise ValueError(f"unknown executor surface: {value}")
        return value


class LaunchCreateRequest(LaunchPreviewRequest):
    item: str = Field(min_length=1, max_length=64)
    instructions: str = ""
    compose_mandate: bool = True
    idempotency_key: str
    sender_surface: Optional[SenderSurface] = None
    presentation: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
    )


class LaunchMutationRequest(BaseModel):
    launch_id: str


class LaunchReconcileRequest(LaunchMutationRequest):
    observed_native_id: Optional[str] = None


class LaunchListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str
    state: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)


class LaunchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    launch: Dict[str, Any]
    preview: Optional[Dict[str, Any]] = None
    deduplicated: bool = False


class LaunchListResponse(BaseModel):
    launches: List[Dict[str, Any]]
    count: int


class LaunchPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    outcome: str
    requested_surface: str
    requested_model: Optional[str] = None
    selected_surface: Optional[str] = None
    fallback_used: bool = False
    launchable: bool
    considered_machine_ids: List[str] = Field(default_factory=list)
    rejection_codes: List[str] = Field(default_factory=list)
    eligible_relays: List[Dict[str, Any]]
    selected_relay: Optional[Dict[str, Any]] = None


__all__ = [
    "ActorMessageRecipient",
    "LaunchCreateRequest",
    "LaunchListRequest",
    "LaunchListResponse",
    "LaunchMutationRequest",
    "LaunchPreviewRequest",
    "LaunchPreviewResponse",
    "LaunchReconcileRequest",
    "LaunchResponse",
    "LaunchState",
    "MessageAcknowledgeRequest",
    "MessageCancelRequest",
    "MessageGetRequest",
    "MessageGetResponse",
    "MessageLeaseCompleteRequest",
    "MessageLeaseRequest",
    "MessageLeaseResponse",
    "MessageListRequest",
    "MessageListResponse",
    "MessageListState",
    "MessageMutationResponse",
    "MessagePreviewRequest",
    "MessagePreviewResponse",
    "MessageRecipient",
    "MessageSendRequest",
    "MessageSendResponse",
    "MessageState",
    "RecipientSelector",
    "RelayClaimRequest",
    "RelayClaimResponse",
    "RelayListRequest",
    "RelayListResponse",
    "RelayLivenessReport",
    "RelayLivenessRequest",
    "RelayLivenessResponse",
    "RelayIdleHost",
    "RelayIdleHostsRequest",
    "RelayIdleHostsResponse",
    "RelayReclaimedHost",
    "RelayReportRequest",
    "RelayReportResponse",
]
