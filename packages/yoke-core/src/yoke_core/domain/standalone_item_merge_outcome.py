"""Native facts returned by a standalone item merge attempt."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.public_item_target import public_item_target

from yoke_contracts.timestamps import as_utc


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
            object.__setattr__(self, "enqueued_at", as_utc(self.enqueued_at))


def sync_item_to_github(item_id: int) -> Optional[str]:
    """Mirror the item to GitHub when its project's sync mode allows it.

    The sync owner already skips projects that do not mirror, so this call is
    unconditional; the return value is advisory and never unwinds a merge.
    """
    response = call_dispatcher(
        function_id="items.github_sync",
        target=public_item_target(item_id),
        payload={},
    )
    if response.success:
        return None
    return (
        response.error.message if response.error is not None else "GitHub sync failed"
    )
