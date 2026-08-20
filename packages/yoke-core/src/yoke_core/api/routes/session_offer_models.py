"""HTTP request models for the session-offer endpoint."""

from __future__ import annotations

from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class SessionOfferRequest(BaseModel):
    """Request body for POST /v1/sessions/offer.

    Carries only what the session row cannot answer. Executor, provider,
    model, workspace, and capabilities are read server-side from the row
    registration wrote, so a caller cannot restate them.

    ``execution_lane`` is the exception, and a deliberate one: it is the
    operator override that routes a session to a different lane on purpose,
    and the server records it as ``SessionOfferLaneOverrideApplied``. An
    autonomous loop sends nothing here — a lane guessed from local config is
    exactly what this field must never carry.

    Extras are forbidden rather than ignored, so a body still sending a
    retired field is told it is gone instead of having it silently dropped.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    step: int = Field(default=1, ge=1)
    execution_lane: Optional[str] = None
    project_scope: Optional[List[Union[str, int]]] = None


__all__ = ["SessionOfferRequest"]
