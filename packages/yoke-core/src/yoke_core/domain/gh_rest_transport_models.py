"""Value objects exchanged with the GitHub REST transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class RestRequest:
    """A single GitHub REST API request.

    ``path`` is an API path or full URL. ``replay_safe`` explicitly declares
    whether a non-idempotent operation may be replayed after an ambiguous
    transport failure; idempotent methods are safe by default.
    """

    method: str
    path: str
    query: Mapping[str, str] = field(default_factory=dict)
    body: Optional[Mapping[str, Any]] = None
    accept: str = "application/vnd.github+json"
    replay_safe: bool | None = None


@dataclass(frozen=True)
class RestResponse:
    """A successful GitHub REST API response."""

    status: int
    headers: Mapping[str, str]
    body: Any


__all__ = ["RestRequest", "RestResponse"]
