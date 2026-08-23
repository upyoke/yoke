"""Typed contract for narrow control-plane migration-content verification."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


FUNCTION_ID = "migration.content_identity.verify"
MAX_CANDIDATE_ENTRIES = 1000
SHA256_PATTERN = r"^[0-9a-fA-F]{64}$"


class MigrationContentCandidate(BaseModel):
    """One permanent migration name and the bytes carried by a candidate."""

    name: str = Field(..., min_length=1, max_length=255)
    content_sha256: str = Field(..., pattern=SHA256_PATTERN)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("migration name must not be blank")
        return stripped


class MigrationContentIdentityVerifyRequest(BaseModel):
    """The complete candidate name/digest set submitted for verification."""

    entries: List[MigrationContentCandidate] = Field(
        ..., min_length=1, max_length=MAX_CANDIDATE_ENTRIES
    )

    @model_validator(mode="after")
    def _require_unique_names(self) -> "MigrationContentIdentityVerifyRequest":
        names = [entry.name for entry in self.entries]
        if len(set(names)) != len(names):
            raise ValueError("candidate migration names must be unique")
        return self


class MigrationContentIdentityVerifyResponse(BaseModel):
    """Non-sensitive identity verdict; live ledger digests never leave the server."""

    status: Literal["verified", "mismatch"]
    verified_count: int = Field(..., ge=0)
    mismatched_entries: List[str] = Field(default_factory=list)


__all__ = [
    "FUNCTION_ID",
    "MAX_CANDIDATE_ENTRIES",
    "MigrationContentCandidate",
    "MigrationContentIdentityVerifyRequest",
    "MigrationContentIdentityVerifyResponse",
    "SHA256_PATTERN",
]
