"""Wire models for Fleet relay claims, liveness, and settlement."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yoke_contracts.session_control.evidence_fetch import EvidenceFileEntry


class RelayClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relay_id: str
    machine_id: str
    hostname: str
    relay_version: str
    projects: List[int]
    surfaces: Dict[str, str]
    plan_limits: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    capacity: Dict[str, Any] = Field(default_factory=dict)
    wait_seconds: int = Field(default=55, ge=0, le=55)
    broker_only: bool = False
    broker_lease_id: Optional[str] = None

    @field_validator("broker_lease_id")
    @classmethod
    def _validate_broker_lease_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        try:
            return str(UUID(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("broker_lease_id must be a UUID") from exc

    @model_validator(mode="after")
    def _require_exact_broker_lease(self) -> "RelayClaimRequest":
        if self.broker_only != bool(self.broker_lease_id):
            raise ValueError(
                "broker_only and broker_lease_id must be provided together"
            )
        return self


class RelayListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: Optional[str] = None
    state: Optional[Literal["active", "idle"]] = None
    limit: int = Field(default=100, ge=1, le=500)


class RelayListResponse(BaseModel):
    relays: List[Dict[str, Any]]
    count: int


class RelayClaimResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    relay_id: str
    machine_id: str
    state: Literal["active", "idle"]
    connected_until: str
    next_poll_seconds: int
    jobs: List[Dict[str, Any]] = Field(default_factory=list)


class RelayLivenessReport(BaseModel):
    """One session whose native process the reporting machine proved gone."""

    model_config = ConfigDict(extra="forbid")
    session_id: str
    evidence: Dict[str, Any] = Field(default_factory=dict)


class RelayLivenessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relay_id: str
    machine_id: str
    projects: List[int]
    sessions: List[RelayLivenessReport] = Field(default_factory=list, max_length=100)


class RelayLivenessResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    ended: List[str] = Field(default_factory=list)
    skipped: List[Dict[str, Any]] = Field(default_factory=list)


class EvidenceDocument(BaseModel):
    """One evidence read's listing and the tail of the file it selected."""

    model_config = ConfigDict(extra="forbid")
    files: List[EvidenceFileEntry] = Field(default_factory=list, max_length=200)
    selected_file: Optional[str] = None
    content: str = ""
    truncated: bool = False


class RelayReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relay_id: str
    job_kind: Literal["wake", "launch", "terminate", "evidence"]
    job_id: str
    lease_id: str
    result: str
    native_id: Optional[str] = None
    adapter_revision: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    #: The listing and file tail an evidence read brings back. Every other
    #: report carries only the bounded ``evidence`` allowlist, which is sized
    #: for short named facts and would silently drop a file's contents.
    document: Optional[EvidenceDocument] = None

    @model_validator(mode="after")
    def _document_belongs_to_evidence(self) -> "RelayReportRequest":
        if self.document is not None and self.job_kind != "evidence":
            raise ValueError("only an evidence report may carry a document")
        return self


class RelayReportResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_kind: Literal["wake", "launch", "terminate", "evidence"]
    result: Dict[str, Any]


__all__ = [
    "EvidenceDocument",
    "RelayClaimRequest",
    "RelayClaimResponse",
    "RelayListRequest",
    "RelayListResponse",
    "RelayLivenessReport",
    "RelayLivenessRequest",
    "RelayLivenessResponse",
    "RelayReportRequest",
    "RelayReportResponse",
]
