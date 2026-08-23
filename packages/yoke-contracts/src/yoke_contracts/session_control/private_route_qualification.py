"""Typed, non-secret scope for one stage-only private-route proof."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS


QUALIFICATION_LEASE_PREFIX = "FLEET_PRIVATE_ROUTE_QUALIFICATION:v1:"
QUALIFICATION_TTL_SECONDS = 30 * 60
QUALIFICATION_RELEASE_REASON = "private_route_qualification_consumed"
QUALIFICATION_ABANDONED_REASON = "private_route_qualification_abandoned"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_OPERATIONS = frozenset({"create", "message_active", "message_idle", "message_stopped"})
_ROUTES = frozenset({"direct", "broker", "hook"})


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class PrivateRouteQualificationScope(BaseModel):
    """Every fact that may authorize exactly one private route operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: Literal["stage"] = "stage"
    release_sha: str
    acceptance_run_id: str
    surface: str
    version: str = Field(min_length=1, max_length=128)
    operation: str
    route: str

    @field_validator("release_sha")
    @classmethod
    def _full_release_sha(cls, value: str) -> str:
        if not _SHA.fullmatch(value):
            raise ValueError("release_sha must be 40 lowercase hex characters")
        return value

    @field_validator("acceptance_run_id")
    @classmethod
    def _run_id(cls, value: str) -> str:
        if not _RUN_ID.fullmatch(value):
            raise ValueError("acceptance_run_id is malformed")
        return value

    @field_validator("surface")
    @classmethod
    def _surface(cls, value: str) -> str:
        if value not in KNOWN_SURFACE_LABELS:
            raise ValueError("surface is unknown")
        return value

    @field_validator("operation")
    @classmethod
    def _operation(cls, value: str) -> str:
        if value not in _OPERATIONS:
            raise ValueError("operation is unknown")
        return value

    @field_validator("route")
    @classmethod
    def _route(cls, value: str) -> str:
        if value not in _ROUTES:
            raise ValueError("route is unknown")
        return value

    @model_validator(mode="after")
    def _compatible_route(self) -> "PrivateRouteQualificationScope":
        if self.route == "hook" and self.operation != "message_active":
            raise ValueError("hook qualification is active-message only")
        if self.operation == "create" and self.route != "direct":
            raise ValueError("create qualification requires a direct route")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @property
    def lease_key(self) -> str:
        encoded = urlsafe_b64encode(self.canonical_bytes()).decode("ascii").rstrip("=")
        return f"{QUALIFICATION_LEASE_PREFIX}{encoded}"

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class PrivateRouteQualificationOpenRequest(PrivateRouteQualificationScope):
    project: str = Field(min_length=1, max_length=128)

    def scope(self) -> PrivateRouteQualificationScope:
        return PrivateRouteQualificationScope.model_validate(
            self.model_dump(exclude={"project"})
        )


class PrivateRouteQualificationGrant(BaseModel):
    """Relay-safe envelope; it carries no message body or credential."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lease_id: int
    project_id: int
    sender_session_id: str
    operator_actor_id: str
    opened_at: str
    expires_at: str
    grant_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: PrivateRouteQualificationScope

    def expired(self, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return current >= _utc(self.expires_at)


class PrivateRouteQualificationOpenResponse(BaseModel):
    grant: PrivateRouteQualificationGrant


def decode_qualification_lease_key(
    lease_key: str,
) -> PrivateRouteQualificationScope | None:
    if not lease_key.startswith(QUALIFICATION_LEASE_PREFIX):
        return None
    encoded = lease_key[len(QUALIFICATION_LEASE_PREFIX) :]
    try:
        padding = "=" * (-len(encoded) % 4)
        raw: Any = json.loads(urlsafe_b64decode(encoded + padding))
        scope = PrivateRouteQualificationScope.model_validate(raw)
    except Exception:
        return None
    return scope if scope.lease_key == lease_key else None


def qualification_expires_at(opened_at: str) -> str:
    value = _utc(opened_at) + timedelta(seconds=QUALIFICATION_TTL_SECONDS)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "QUALIFICATION_LEASE_PREFIX",
    "QUALIFICATION_ABANDONED_REASON",
    "QUALIFICATION_RELEASE_REASON",
    "QUALIFICATION_TTL_SECONDS",
    "PrivateRouteQualificationGrant",
    "PrivateRouteQualificationOpenRequest",
    "PrivateRouteQualificationOpenResponse",
    "PrivateRouteQualificationScope",
    "decode_qualification_lease_key",
    "qualification_expires_at",
]
