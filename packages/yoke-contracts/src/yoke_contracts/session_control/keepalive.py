"""Wire models for holding a claim-free session alive against idle reaping."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


#: Longest a single hold may run. A lease nobody renews has to expire on its
#: own, and an hour is long enough for the acceptance run that motivated this
#: while still being a window an operator can wait out. The wire boundary, the
#: domain writer, and the CLI all read the bound from here.
MAX_KEEPALIVE_SECONDS = 3600

#: What a caller gets when it names no window of its own.
DEFAULT_KEEPALIVE_SECONDS = 900


class SessionKeepaliveHoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2000)
    seconds: int = Field(
        default=DEFAULT_KEEPALIVE_SECONDS, ge=1, le=MAX_KEEPALIVE_SECONDS
    )

    @field_validator("reason")
    @classmethod
    def _nonblank_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("reason must not be blank")
        return reason


class SessionKeepaliveReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=255)


class SessionKeepaliveResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    session_id: str
    held: bool
    keepalive_until: Optional[str] = None
    keepalive_reason: Optional[str] = None
    session: Optional[Dict[str, Any]] = None


__all__ = [
    "DEFAULT_KEEPALIVE_SECONDS",
    "MAX_KEEPALIVE_SECONDS",
    "SessionKeepaliveHoldRequest",
    "SessionKeepaliveReleaseRequest",
    "SessionKeepaliveResponse",
]
