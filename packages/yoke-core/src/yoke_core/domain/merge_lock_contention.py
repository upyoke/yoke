"""Who a merge contends with, and whether a holder is still real.

Deciding contention needs three things that have nothing to do with where
the lock rows are stored: the scope a merge occupies, whether a recorded
holder is still alive, and how to say so. Keeping them here lets one
evaluator serve both row sources — a local Postgres connection and a
relayed read over an https control plane.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class LockScope:
    """What a merge actually contends for: one branch of one project.

    Two merges collide only when they land on the same ``target_branch`` of
    the same ``project_slug``. An unscoped lock — a row written before the
    scope was recorded, or a caller that could not resolve its project —
    contends with everything, because "scope unknown" must never be read as
    "scope compatible". The safe failure direction for a merge lock is to
    over-serialize, never to let two merges land on one branch at once.
    """

    project_slug: Optional[str] = None
    target_branch: Optional[str] = None

    @property
    def is_known(self) -> bool:
        return bool(self.project_slug and self.target_branch)

    def contends_with(self, other: "LockScope") -> bool:
        if not self.is_known or not other.is_known:
            return True
        return (
            self.project_slug == other.project_slug
            and self.target_branch == other.target_branch
        )


@dataclass(frozen=True)
class ContentionVerdict:
    """What the caller should do about the rows it just read."""

    blocked_by: Optional[str]
    stale_ids: tuple[int, ...]


def holder_is_alive(session_id: str) -> bool:
    """Is the process that took this lock still running on this machine?

    A holder id is ``<pid>-<epoch>``. An id we cannot parse is treated as
    alive: an unreadable holder is not evidence of a dead one.
    """
    try:
        pid = int(str(session_id).split("-", 1)[0])
    except (ValueError, IndexError):
        return True
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except (OSError, ValueError):
        return False


def blocking_message(session_id: str, branch: str, epic_id: str) -> str:
    epic_info = f" (epic: {epic_id})" if epic_id else ""
    return (
        f"Merge lock held by session {session_id} "
        f"on branch '{branch}'{epic_info}"
    )


def evaluate(
    rows: Sequence[Mapping[str, Any]],
    scope: LockScope,
) -> ContentionVerdict:
    """Judge the lock rows against *scope*.

    Rows outside the scope are skipped entirely — not reported, and not
    retired, because they belong to a live merge somewhere else and are not
    this caller's to judge.
    """
    blocked_by: Optional[str] = None
    stale_ids: list[int] = []
    for row in rows:
        row_scope = LockScope(
            row.get("project_slug") or None,
            row.get("target_branch") or None,
        )
        if not scope.contends_with(row_scope):
            continue
        session_id = str(row.get("session_id") or "")
        if not holder_is_alive(session_id):
            stale_ids.append(int(row["id"]))
            continue
        blocked_by = blocking_message(
            session_id,
            str(row.get("branch") or ""),
            str(row.get("epic_id") or ""),
        )
    return ContentionVerdict(blocked_by, tuple(stale_ids))


__all__ = [
    "ContentionVerdict",
    "LockScope",
    "blocking_message",
    "evaluate",
    "holder_is_alive",
]
