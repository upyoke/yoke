"""Native facts returned by a standalone item merge attempt."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from yoke_contracts.timestamps import parse_instant


@dataclass(frozen=True)
class StandaloneMergeOutcome:
    """What one standalone merge attempt produced."""

    ok: bool
    exit_code: int
    already_merged: bool
    commit_sha: str = ""
    merge_sha: str = ""
    touched_files: tuple[str, ...] = ()
    pushed: bool = False
    landing_pending: bool = False
    pr_num: str = ""
    enqueued_at: datetime | None = None
    error: str = ""
    output: str = ""
    publication_message: str = ""
    warnings: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.enqueued_at is not None:
            object.__setattr__(self, "enqueued_at", parse_instant(self.enqueued_at))
