"""Wire models for an explicit native session wake."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EXPLICIT_WAKE_ROUTING_FLAG = "explicit_stopped_wake"


class SessionWakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    item_ref: Optional[str] = Field(default=None, min_length=1, max_length=100)
    prompt: Optional[str] = Field(default=None, max_length=1_000_000)
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=255)

    @field_validator("session_id", "item_ref", "prompt", "idempotency_key")
    @classmethod
    def _nonblank_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        rendered = value.strip()
        if not rendered:
            raise ValueError("value must not be blank")
        return rendered

    @model_validator(mode="after")
    def _one_target(self) -> "SessionWakeRequest":
        if bool(self.session_id) == bool(self.item_ref):
            raise ValueError("exactly one of session_id or item_ref is required")
        return self


class SessionWakeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    target_session_id: str
    target_liveness: str
    message_id: str
    result_code: str
    attempt: Optional[Dict[str, Any]] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    recovery: Optional[str] = None
    deduplicated: bool = False
    wake_attempt_count: int = 0
    last_wake_at: Optional[str] = None


__all__ = [
    "EXPLICIT_WAKE_ROUTING_FLAG",
    "SessionWakeRequest",
    "SessionWakeResponse",
]
