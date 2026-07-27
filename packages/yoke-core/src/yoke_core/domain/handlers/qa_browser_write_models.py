"""Typed payloads for Browser QA run and artifact writes."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class QaRunAddRequest(BaseModel):
    executor_type: str
    qa_kind: Optional[str] = None
    verdict: Optional[str] = None
    execution_status: Optional[str] = None
    raw_result: Optional[str] = None
    duration_ms: Optional[int] = None


class QaRunAddResponse(BaseModel):
    qa_run_id: int
    requirement_id: int


class QaRunCompleteRequest(BaseModel):
    run_id: int
    verdict: Optional[str] = None
    execution_status: Optional[str] = None
    raw_result: Optional[str] = None
    duration_ms: Optional[int] = None


class QaRunCompleteResponse(BaseModel):
    qa_run_id: int


class QaArtifactAddRequest(BaseModel):
    run_id: int
    artifact_type: str
    artifact_handle: dict
    content_type: Optional[str] = None
    metadata: Optional[str] = None


class QaArtifactAddResponse(BaseModel):
    qa_artifact_id: int


__all__ = [
    "QaArtifactAddRequest",
    "QaArtifactAddResponse",
    "QaRunAddRequest",
    "QaRunAddResponse",
    "QaRunCompleteRequest",
    "QaRunCompleteResponse",
]
