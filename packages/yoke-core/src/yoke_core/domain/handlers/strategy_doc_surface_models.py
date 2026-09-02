"""Typed contracts for strategy review and Blitz document execution."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategySurfaceGetRequest(BaseModel):
    slug: str = Field(..., min_length=1)


class StrategySurfaceListResponse(BaseModel):
    project_id: int
    project_slug: str
    docs: List[Dict[str, Any]] = Field(default_factory=list)
    writes: List[Dict[str, Any]] = Field(default_factory=list)


class StrategySurfaceGetResponse(BaseModel):
    project_id: int
    project_slug: str
    document: Dict[str, Any]


class StrategyRevisionDiffRequest(BaseModel):
    slug: str = Field(..., min_length=1)
    from_revision: int = Field(..., gt=0)
    to_revision: int = Field(..., gt=0)


class StrategyRevisionDiffResponse(BaseModel):
    project_id: int
    project_slug: str
    comparison: Dict[str, Any]


class StrategyRevisionRestoreRequest(BaseModel):
    slug: str = Field(..., min_length=1)
    revision: int = Field(..., gt=0)
    base_updated_at: str = Field(..., min_length=1)


class StrategyRevisionRestoreResponse(BaseModel):
    project_id: int
    project_slug: str
    result: Dict[str, Any]


class StrategyParentSetRequest(BaseModel):
    slug: str = Field(..., min_length=1)
    parent_slug: Optional[str] = None


class StrategyParentSetResponse(BaseModel):
    project_id: int
    project_slug: str
    result: Dict[str, Any]


class StrategyCoordinationAppendRequest(BaseModel):
    slug: str = Field(..., min_length=1)
    section: str = Field(..., min_length=1)
    entry: str = Field(..., min_length=1)


class StrategyCoordinationAppendResponse(BaseModel):
    project_id: int
    project_slug: str
    result: Dict[str, Any]


class StrategyExecutionLinkRequest(BaseModel):
    slug: str = Field(..., min_length=1)


class StrategyExecutionResponse(BaseModel):
    item_id: int
    execution: Dict[str, Any]


class StrategyExecutionClaimReleaseRequest(BaseModel):
    reason: Optional[str] = None


class StrategyExecutionClaimBreakGlassRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class StrategyDocClaimAcquireRequest(BaseModel):
    slug: str = Field(..., min_length=1)
    reason: Optional[str] = None


class StrategyDocClaimReleaseRequest(BaseModel):
    slug: str = Field(..., min_length=1)
    reason: Optional[str] = None


class StrategyDocClaimListRequest(BaseModel):
    active_only: bool = True


class StrategyDocClaimResponse(BaseModel):
    project_id: int
    project_slug: str
    claim: Dict[str, Any]


class StrategyDocClaimListResponse(BaseModel):
    project_id: int
    project_slug: str
    claims: List[Dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "EmptyRequest",
    "StrategyDocClaimAcquireRequest",
    "StrategyDocClaimListRequest",
    "StrategyDocClaimListResponse",
    "StrategyDocClaimReleaseRequest",
    "StrategyDocClaimResponse",
    "StrategyCoordinationAppendRequest",
    "StrategyCoordinationAppendResponse",
    "StrategyExecutionClaimReleaseRequest",
    "StrategyExecutionClaimBreakGlassRequest",
    "StrategyExecutionLinkRequest",
    "StrategyExecutionResponse",
    "StrategyParentSetRequest",
    "StrategyParentSetResponse",
    "StrategyRevisionDiffRequest",
    "StrategyRevisionDiffResponse",
    "StrategyRevisionRestoreRequest",
    "StrategyRevisionRestoreResponse",
    "StrategySurfaceGetRequest",
    "StrategySurfaceGetResponse",
    "StrategySurfaceListResponse",
]
