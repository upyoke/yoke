"""Name GitHub Actions runs that are pending without any jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from yoke_contracts.timestamps import as_utc, format_instant, parse_instant, utc_now


PENDING_ZERO_JOBS_STALL_SECONDS = 120
PENDING_ZERO_JOBS_STALL_REASON = "pending_zero_jobs_stall"
STALLED_DISPATCH_TOKEN = "stalled_dispatch"
CI_RUN_NEVER_STARTED_REASON = "ci_run_never_started"


def pending_run_message(
    *,
    repo: str,
    run_id: str,
    jobs_count: int,
    updated_at: datetime | str | None,
    observed_at: Optional[datetime] = None,
    concurrency_groups: Optional[tuple[str, ...]] = None,
) -> str:
    """Name a stall only after a complete read rules out concurrency waits."""
    now = utc_now() if observed_at is None else as_utc(observed_at)
    updated = None if updated_at is None else parse_instant(updated_at)
    updated_text = "unknown" if updated is None else format_instant(updated)
    age_seconds = (now - updated).total_seconds() if updated is not None else -1
    detail = f"pending run={run_id} jobs={jobs_count} updated_at={updated_text}"
    if concurrency_groups is None:
        return detail
    if concurrency_groups:
        return f"{detail} waiting_on=concurrency groups={','.join(concurrency_groups)}"
    if jobs_count != 0 or age_seconds < PENDING_ZERO_JOBS_STALL_SECONDS:
        return detail
    return (
        f"{STALLED_DISPATCH_TOKEN} "
        f"waiting_on={PENDING_ZERO_JOBS_STALL_REASON} "
        f"failure_reason={CI_RUN_NEVER_STARTED_REASON} "
        f"run={run_id} status=pending jobs=0 updated_at={updated_text}; "
        "force-cancel with `gh api --method POST "
        f"repos/{repo}/actions/runs/{run_id}/force-cancel`"
    )


def run_concurrency_groups(data: object) -> tuple[str, ...]:
    """Require complete queue evidence; missing evidence cannot prove a stall.

    A configured group still explains waiting when its membership is empty:
    GitHub can be between releasing the holder and admitting this run.
    """
    if not isinstance(data, dict):
        raise ValueError("concurrency response must be an object")
    groups = data.get("concurrency_groups")
    count = data.get("total_count")
    if (
        not isinstance(groups, list)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(groups)
    ):
        raise ValueError("concurrency response omitted a complete group listing")
    names = []
    for group in groups:
        if not isinstance(group, dict) or not group.get("group_name"):
            raise ValueError("concurrency response omitted a group name")
        names.append(str(group["group_name"]))
    return tuple(names)


__all__ = [
    "CI_RUN_NEVER_STARTED_REASON",
    "PENDING_ZERO_JOBS_STALL_REASON",
    "PENDING_ZERO_JOBS_STALL_SECONDS",
    "STALLED_DISPATCH_TOKEN",
    "pending_run_message",
    "run_concurrency_groups",
]
