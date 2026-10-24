"""Typed epic task and dispatch-chain operation payloads."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class EmptyRequest(BaseModel):
    """No payload."""


class PhaseRequest(BaseModel):
    phase: str = Field(..., min_length=1)


class HistoryInsertRequest(BaseModel):
    from_status: str = Field(..., min_length=1)
    to_status: str = Field(..., min_length=1)
    note: str = ""


class ChainWorktreeRequest(BaseModel):
    worktree: str = Field(..., min_length=1)


class ChainUpdateRequest(BaseModel):
    worktree: str = Field(..., min_length=1)
    field: str = Field(..., min_length=1)
    value: str = ""


class ChainRefreshActivationRequest(BaseModel):
    worktree: str = Field(..., min_length=1)
    task_num: int = Field(..., ge=1)


class BodyResponse(BaseModel):
    epic_id: int
    body: str


class HeadDispatch(BaseModel):
    task_num: Optional[int] = None
    decision: Literal["resumable", "busy", "blocked", "unknown"]
    reason: str
    holder_session_id: Optional[str] = None


class ChainReadResponse(BodyResponse):
    head_dispatch: List[HeadDispatch] = Field(default_factory=list)


class TaskBodyResponse(BodyResponse):
    task_num: int


class MessageResponse(BaseModel):
    epic_id: int
    task_num: Optional[int] = None
    message: str


def operation_registration(
    fid: str,
    handler: Any,
    req: Any,
    resp: Any,
    effects: List[str],
    claim: Optional[str],
    *,
    owner: str,
) -> Dict[str, Any]:
    return {
        "function_id": fid,
        "handler": handler,
        "request_model": req,
        "response_model": resp,
        "stability": "stable",
        "owner_module": owner,
        "target_kinds": ["epic_task"],
        "side_effects": effects,
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": claim,
    }
