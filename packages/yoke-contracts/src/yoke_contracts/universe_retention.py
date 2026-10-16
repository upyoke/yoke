"""Validated retention settings and stateless foreground pass messages."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yoke_contracts.retention_defaults import (
    DEFAULT_EVENT_DAYS,
    DEFAULT_SEVERITY_DAYS,
    DEFAULT_WINDOWS,
)
from yoke_contracts.timestamps import parse_instant

Days = Annotated[int, Field(strict=True, ge=1, le=36500)]


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    severity_days: dict[str, Days] = Field(
        default_factory=lambda: dict(DEFAULT_SEVERITY_DAYS)
    )
    event_days: dict[str, Days] = Field(
        default_factory=lambda: dict(DEFAULT_EVENT_DAYS)
    )
    windows: dict[str, Days] = Field(default_factory=lambda: dict(DEFAULT_WINDOWS))
    batch_rows: Annotated[int, Field(strict=True, ge=1, le=5000)] = 5000
    pass_seconds: Annotated[float, Field(strict=True, gt=0, le=20)] = 8.0
    statement_seconds: Annotated[float, Field(strict=True, gt=0, le=10)] = 10.0
    lock_seconds: Annotated[float, Field(strict=True, gt=0, le=1)] = 1.0

    @field_validator("severity_days", "windows")
    @classmethod
    def known_keys(cls, value, info):
        expected = (
            DEFAULT_SEVERITY_DAYS
            if info.field_name == "severity_days"
            else DEFAULT_WINDOWS
        )
        if set(value) != set(expected):
            raise ValueError(
                f"{info.field_name} must contain exactly {', '.join(expected)}"
            )
        return value

    @field_validator("event_days")
    @classmethod
    def event_names(cls, value):
        if any(not name or len(name) > 200 for name in value):
            raise ValueError("event override names must have 1–200 characters")
        return value

    @model_validator(mode="after")
    def safety_windows(self):
        if self.windows["replay"] < 7:
            raise ValueError("replay retention must preserve the seven-day guarantee")
        if self.windows["snapshot_uploads"] > 7:
            raise ValueError("snapshot upload staging has a maximum seven-day lifetime")
        return self

    @property
    def digest(self) -> str:
        raw = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


class RetentionReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PruneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apply: bool = False
    cutoff: datetime | None = None
    expected_digest: str | None = None
    table_index: Annotated[int, Field(strict=True, ge=0)] = 0
    # Tables this invocation has finished (nothing eligible under its fixed
    # cutoff) or stopped retrying after repeated statement/lock limits.
    skip_tables: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("cutoff", mode="before")
    @classmethod
    def qualified_clock(cls, value):
        return None if value is None else parse_instant(value)


class RetentionResponse(BaseModel):
    universe: dict
    source: str
    policy: dict
    policy_digest: str
    cutoff: str


class PruneResponse(RetentionResponse):
    tables: list[dict] = Field(default_factory=list)
    skipped: list[dict] = Field(default_factory=list)
    next_table_index: int = 0
    cycle_complete: bool = False
    failure: dict | None = None
