"""HTTP request models for the session-offer endpoint."""

from __future__ import annotations

from typing import List, Optional, Union

from pydantic import BaseModel, Field


class SessionOfferRequest(BaseModel):
    """Request body for POST /v1/sessions/offer."""

    session_id: str
    executor: str
    provider: str
    model: str
    capabilities: Optional[List[str]] = None
    workspace: str
    execution_lane: Optional[str] = None
    step: int = Field(default=1, ge=1)
    supported_paths: Optional[List[str]] = None
    project_scope: Optional[List[Union[str, int]]] = None


__all__ = ["SessionOfferRequest"]
