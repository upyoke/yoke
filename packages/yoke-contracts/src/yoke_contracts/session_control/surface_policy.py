"""Wire models for steerer-managed per-machine surface disable marks."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS


SURFACE_POLICY_STATE_DISABLED = "disabled"
SurfacePolicyState = Literal["disabled"]


def _require_known_surface(value: str) -> str:
    surface = str(value or "").strip()
    if surface not in KNOWN_SURFACE_LABELS:
        raise ValueError(f"unknown executor surface: {surface}")
    return surface


class SurfacePolicyMark(BaseModel):
    model_config = ConfigDict(extra="allow")
    mark_id: str
    machine_id: str
    surface: str
    state: SurfacePolicyState
    reason: str
    evidence: Optional[str] = None
    set_by_actor_id: int
    set_by_session_id: Optional[str] = None
    created_at: str
    cleared_at: Optional[str] = None
    cleared_by_actor_id: Optional[int] = None


class SurfacePolicySetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str
    machine_id: str
    surface: str
    reason: str = Field(min_length=1, max_length=200)
    evidence: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("machine_id")
    @classmethod
    def _machine(cls, value: str) -> str:
        machine_id = str(value or "").strip()
        if not machine_id:
            raise ValueError("machine_id is required")
        return machine_id

    @field_validator("surface")
    @classmethod
    def _surface(cls, value: str) -> str:
        return _require_known_surface(value)


class SurfacePolicyClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str
    machine_id: str
    surface: str

    @field_validator("machine_id")
    @classmethod
    def _machine(cls, value: str) -> str:
        machine_id = str(value or "").strip()
        if not machine_id:
            raise ValueError("machine_id is required")
        return machine_id

    @field_validator("surface")
    @classmethod
    def _surface(cls, value: str) -> str:
        return _require_known_surface(value)


class SurfacePolicyListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: Optional[str] = None
    surface: Optional[str] = None
    include_cleared: bool = False

    @field_validator("surface")
    @classmethod
    def _surface(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        return _require_known_surface(value)


class SurfacePolicyMutationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    mark: SurfacePolicyMark


class SurfacePolicyListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    marks: List[SurfacePolicyMark] = Field(default_factory=list)
    count: int = 0


__all__ = [
    "SURFACE_POLICY_STATE_DISABLED",
    "SurfacePolicyClearRequest",
    "SurfacePolicyListRequest",
    "SurfacePolicyListResponse",
    "SurfacePolicyMark",
    "SurfacePolicyMutationResponse",
    "SurfacePolicySetRequest",
    "SurfacePolicyState",
]
