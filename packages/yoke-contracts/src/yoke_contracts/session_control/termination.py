"""Wire models for permanent session termination."""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionTerminateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _nonblank_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("reason must not be blank")
        return reason


class SessionTerminateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    session: Dict[str, Any]
    cancelled_recipient_count: int = 0
    reap_state: str
    deduplicated: bool = False


__all__ = ["SessionTerminateRequest", "SessionTerminateResponse"]
