"""Internal records and typed failures for the session message plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class SessionMessageError(ValueError):
    """A message operation failed with a stable product outcome code."""

    def __init__(self, code: str, message: str, *, jsonpath: str = "$.payload"):
        super().__init__(message)
        self.code = code
        self.jsonpath = jsonpath


@dataclass
class ResolvedRecipient:
    """One deduplicated top-level session plus its immutable routing facts."""

    session_id: str
    project_id: int
    project: str
    executor: str
    executor_surface: str | None
    executor_version: str | None
    machine_id: str | None
    liveness: str
    messageability: dict[str, Any]
    resolution: list[str] = field(default_factory=list)
    authorized_project_ids: set[int] = field(default_factory=set)
    work_roles: set[str] = field(default_factory=set)
    worktree_lanes: set[str] = field(default_factory=set)
    execution_lane: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "project": self.project,
            "executor": self.executor,
            "executor_surface": self.executor_surface,
            "machine_id": self.machine_id,
            "liveness": self.liveness,
            "messageability": dict(self.messageability),
            "resolution": sorted(set(self.resolution)),
        }

    def routing_snapshot(self) -> dict[str, Any]:
        return {
            **self.public(),
            "project_id": self.project_id,
            "authorized_project_ids": sorted(self.authorized_project_ids),
            "executor_version": self.executor_version,
            "execution_lane": self.execution_lane,
            "work_roles": sorted(self.work_roles),
            "worktree_lanes": sorted(self.worktree_lanes),
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return as_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def timestamp(value: datetime) -> str:
    return as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def row_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    raise TypeError("session message queries require name-aware rows")


__all__ = [
    "ResolvedRecipient",
    "SessionMessageError",
    "as_utc",
    "parse_timestamp",
    "row_dict",
    "timestamp",
    "utc_now",
]
