"""Request and response models for ``claims.path.*`` handlers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    item_id: Optional[int] = None
    integration_target: Optional[str] = None
    paths: List[str] = Field(default_factory=list)
    mode: str = "exclusive"
    exception_reason: Optional[str] = None
    allow_planned: bool = False
    directory_paths: Optional[List[str]] = None
    tentative_paths: Optional[List[str]] = None
    upstream_claim_id: Optional[int] = None
    actor_id: Optional[int] = None
    task_num: Optional[int] = Field(default=None, ge=1)


class RegisterResponse(BaseModel):
    claim_id: int


class WidenRequest(BaseModel):
    claim_id: int
    add_target_ids: List[int] = Field(default_factory=list)
    add_paths: List[str] = Field(default_factory=list)
    reason: str = Field(..., min_length=1)
    repo_path: Optional[str] = None
    worktree_head: Optional[str] = None
    allow_planned: bool = False
    directory_paths: Optional[List[str]] = None
    db_claim: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Full unified db_claim amendment payload required when new "
            "coverage enters migration territory without a matching claim."
        ),
    )


class WidenResponse(BaseModel):
    amendment_id: int
    migration_model: Optional[str] = None
    migration_lease_id: Optional[int] = None
    db_claim_event_id: Optional[str] = None


class ReleaseRequest(BaseModel):
    claim_id: int
    reason: str = Field(..., min_length=1)


class ReleaseResponse(BaseModel):
    claim_id: int
    state: str
    released_at: Optional[str] = None


class OverrideRequest(BaseModel):
    path_claim_id: int
    override_point: str = "creation"
    integration_target: str
    actor_id: int
    actor_reason: str = Field(..., min_length=1)
    blocking_claim_id: Optional[int] = None
    blocking_path_targets: Optional[List[int]] = None
    conflict_reason: Optional[str] = None
    item_id: Optional[int] = None
    project: Optional[str] = None


class OverrideResponse(BaseModel):
    override_event_id: Optional[str] = None


__all__ = [
    "OverrideRequest",
    "OverrideResponse",
    "RegisterRequest",
    "RegisterResponse",
    "ReleaseRequest",
    "ReleaseResponse",
    "WidenRequest",
    "WidenResponse",
]
