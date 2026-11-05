"""Bounded first-line counts for hook and watcher fleet deliveries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from yoke_core.domain.steering_fleet_report_compose import CombinedFleetReport


def headline_line(combined: CombinedFleetReport, prior: Mapping[str, Any]) -> str:
    """Summarize new work and distinct actionable findings in under 200 chars."""
    available = prior.get("available_ids", {})
    if not isinstance(available, dict):
        available = {}
    entries: list[tuple[str, str]] = []
    for section in combined.sections:
        previous = available.get(section.descriptor, [])
        if not isinstance(previous, list):
            previous = []
        new_ids = {row.item_id for row in section.report.available} - set(previous)
        if new_ids:
            label = " ".join(section.descriptor.split(" · ", 1)[0].split())
            prefix = "new available " if not entries else ""
            entries.append(
                (" · " if not entries else ", ", f"{prefix}{label} {len(new_ids)}")
            )
    runs = {
        row.run_id
        for section in combined.sections
        for row in section.report.runs_needing_action()
    }
    undelivered = {
        row.session_id
        for section in combined.sections
        for row in section.report.undelivered_needing_action()
    }
    for label, count in (
        ("questions", len(combined.questions)),
        ("runs needing a decision", len(runs)),
        ("undelivered", len(undelivered)),
    ):
        if count:
            entries.append((" · ", f"{label} {count}"))
    if not entries:
        return "headline: no change"
    line = "headline: "
    for index, (separator, value) in enumerate(entries):
        candidate = line + (separator if index else "") + value
        remaining = len(entries) - index - 1
        suffix = f" · +{remaining} more" if remaining else ""
        if len(candidate + suffix) >= 200:
            return line + (" · " if index else "") + f"+{len(entries) - index} more"
        line = candidate
    return line
