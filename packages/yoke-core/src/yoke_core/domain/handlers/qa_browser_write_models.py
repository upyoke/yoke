"""Typed payloads for Browser QA run and artifact writes.

``execution_claim_id`` is the claim a long gate run bound when it started
(see :mod:`yoke_core.domain.qa_start_bound_authority`, whose ``PAYLOAD_KEY``
names this same field). The dispatcher reads it to authorize a recording
leg whose live claim was reclaimed or handed off while the run was still
going; the handlers themselves never consult it.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class QaRunAddRequest(BaseModel):
    performed_by: str
    qa_kind: Optional[str] = None
    verdict: Optional[str] = None
    execution_status: Optional[str] = None
    raw_result: Optional[str] = None
    duration_ms: Optional[int] = None
    execution_claim_id: Optional[int] = None


class QaRunAddResponse(BaseModel):
    qa_run_id: int
    requirement_id: int


class QaRunCompleteRequest(BaseModel):
    run_id: int
    verdict: Optional[str] = None
    execution_status: Optional[str] = None
    raw_result: Optional[str] = None
    duration_ms: Optional[int] = None
    execution_claim_id: Optional[int] = None


class QaRunCompleteResponse(BaseModel):
    qa_run_id: int


class QaArtifactAddRequest(BaseModel):
    run_id: int
    artifact_type: str
    artifact_handle: dict
    content_type: Optional[str] = None
    metadata: Optional[str] = None
    execution_claim_id: Optional[int] = None


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
