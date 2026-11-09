"""Native GitHub pull-request landing facts shared by REST and GraphQL readers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from yoke_contracts.timestamps import parse_instant


@dataclass(frozen=True)
class PrLandingState:
    """Merged/closed facts for one PR, read for queue-outcome polling."""

    merged: bool
    closed: bool
    auto_merge_active: bool
    merge_state_status: str = ""
    head_sha: str = ""
    #: When GitHub merged it, so a reader that arrives late records the
    #: landing's own moment rather than the moment it noticed.
    merged_at: datetime | None = None
    merge_commit_sha: str = ""
    head_branch: str = ""
    target_branch: str = ""
    queue_entry_state: str = "absent"
    auto_merge_enabled_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.auto_merge_enabled_at is not None:
            object.__setattr__(
                self, "auto_merge_enabled_at", parse_instant(self.auto_merge_enabled_at)
            )
        if self.merged_at is not None:
            object.__setattr__(self, "merged_at", parse_instant(self.merged_at))


__all__ = ["PrLandingState"]
