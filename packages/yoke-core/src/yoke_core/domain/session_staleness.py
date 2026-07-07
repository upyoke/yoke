"""Shared executor-aware session staleness predicates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional

from .sessions_analytics_core import DEFAULT_STALE_THRESHOLD_MINUTES
from .sessions_render_reclaim import _resolve_effective_ttl


def _parse_timestamp(value: object) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def activity_is_stale(
    activity_at: object,
    *,
    executor: Optional[str],
    now: Optional[datetime] = None,
    base_ttl_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    executor_ttl_overrides: Optional[Mapping[str, int]] = None,
) -> bool:
    """Return whether ``activity_at`` is stale for the executor's TTL."""
    parsed = _parse_timestamp(activity_at)
    if parsed is None:
        return True
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    ttl = _resolve_effective_ttl(
        executor,
        base_ttl_minutes,
        dict(executor_ttl_overrides) if executor_ttl_overrides is not None else None,
    )
    return parsed < now_dt.astimezone(timezone.utc) - timedelta(minutes=ttl)
