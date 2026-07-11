"""Wire contract for narrowly scoped runner-fleet repository tokens."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RunnerFleetTokenRequest(BaseModel):
    """Bind token issuance to one canonical renderer-authority snapshot."""

    model_config = ConfigDict(extra="forbid")

    authority_sha256: str

    @field_validator("authority_sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        selected = str(value or "").strip().lower()
        if len(selected) != 64 or any(
            character not in "0123456789abcdef" for character in selected
        ):
            raise ValueError("authority_sha256 must be a 64-character SHA-256 digest")
        return selected


class RunnerFleetTokenResponse(BaseModel):
    """One repository-scoped installation token held only in process memory."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(repr=False)
    expires_at: str
    repository: str


__all__ = ["RunnerFleetTokenRequest", "RunnerFleetTokenResponse"]
