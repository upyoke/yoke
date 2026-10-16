"""Paid extra usage as the steering report and session reads print it.

Each machine surface carries one account-wide extra-usage fact beside its
included windows. These helpers phrase it once, with staleness applied, so
every report states the same answer the availability rule acted on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.extra_usage import (
    extra_usage_label,
    sanitize_extra_usage,
)
from yoke_contracts.session_control.model_billing_pools import extra_usage_status


def extra_label_now(row: Any, *, now: datetime | str) -> str:
    """The shared phrase for one plan-limit row's surface, as of ``now``."""
    status = extra_usage_status(row.extra_usage, observed_at=row.observed_at, now=now)
    return extra_usage_label(sanitize_extra_usage(row.extra_usage), status)


def extra_usage_lines(rows: Sequence[Any], *, now: datetime | str) -> list[str]:
    """One line per machine surface, in the order the rows arrive."""
    seen: dict[tuple[str, str], Any] = {}
    for row in rows:
        seen.setdefault((row.machine_name, row.surface), row)
    return [
        f"extra usage · {machine} · {surface}: {extra_label_now(row, now=now)}"
        for (machine, surface), row in seen.items()
    ]


def with_extra_usage_labels(
    plan_limits: Mapping[str, Mapping[str, Any]], *, now: datetime | str
) -> dict[str, dict[str, Any]]:
    """Add each reading's extra-usage status and phrase as of ``now``.

    The Machines panel prints this phrase rather than rebuilding it, so the
    panel and the availability rule cannot disagree.
    """
    labelled: dict[str, dict[str, Any]] = {}
    for surface, reading in plan_limits.items():
        extra = reading.get("extra_usage")
        status = extra_usage_status(
            extra, observed_at=reading.get("observed_at"), now=now
        )
        labelled[surface] = {
            **reading,
            "extra_usage_status": status,
            "extra_usage_label": extra_usage_label(sanitize_extra_usage(extra), status),
        }
    return labelled


__all__ = ["extra_label_now", "extra_usage_lines", "with_extra_usage_labels"]
