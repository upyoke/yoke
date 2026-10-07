"""Typed epic task and dispatch-chain operation payloads."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class EmptyRequest(BaseModel):
    """No payload."""


class PhaseRequest(BaseModel):
    phase: str = Field(..., min_length=1)


class FileAddRequest(BaseModel):
    file_path: str = Field(..., min_length=1)
    action: str = ""

    @field_validator("file_path")
    @classmethod
    def _nonblank_file_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("file_path must name a nonblank path")
        return normalized


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
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": claim,
    }
