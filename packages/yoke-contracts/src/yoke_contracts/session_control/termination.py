"""Wire models for permanent session termination."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SessionTerminateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2000)
    override_chain_end: bool = False
    chain_end_rationale: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _nonblank_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("reason must not be blank")
        return reason

    @model_validator(mode="after")
    def _require_override_rationale(self) -> "SessionTerminateRequest":
        if self.override_chain_end and not str(self.chain_end_rationale or "").strip():
            raise ValueError("chain_end_rationale is required with override_chain_end")
        return self


class SessionTerminateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    session: Dict[str, Any]
    cancelled_recipient_count: int = 0
    reap_state: str
    deduplicated: bool = False


__all__ = ["SessionTerminateRequest", "SessionTerminateResponse"]
