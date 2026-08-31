"""Name GitHub Actions runs that are pending without any jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


PENDING_ZERO_JOBS_STALL_SECONDS = 120
PENDING_ZERO_JOBS_STALL_REASON = "pending_zero_jobs_stall"
STALLED_DISPATCH_TOKEN = "stalled_dispatch"


def _timestamp(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def pending_run_message(
    *,
    repo: str,
    run_id: str,
    jobs_count: int,
    updated_at: str,
    observed_at: Optional[datetime] = None,
) -> str:
    """Describe a pending run, naming a stale zero-job dispatch as a stall."""
    now = observed_at or datetime.now(timezone.utc)
    updated = _timestamp(updated_at)
    age_seconds = (now - updated).total_seconds() if updated is not None else -1
    detail = (
        f"pending run={run_id} jobs={jobs_count} updated_at={updated_at or 'unknown'}"
    )
    if jobs_count != 0 or age_seconds < PENDING_ZERO_JOBS_STALL_SECONDS:
        return detail
    return (
        f"{STALLED_DISPATCH_TOKEN} "
        f"waiting_on={PENDING_ZERO_JOBS_STALL_REASON} "
        f"run={run_id} status=pending jobs=0 updated_at={updated_at}; "
        "force-cancel with `gh api --method POST "
        f"repos/{repo}/actions/runs/{run_id}/force-cancel`"
    )


__all__ = [
    "PENDING_ZERO_JOBS_STALL_REASON",
    "PENDING_ZERO_JOBS_STALL_SECONDS",
    "STALLED_DISPATCH_TOKEN",
    "pending_run_message",
]
