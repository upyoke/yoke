"""Shared section delta for hook and watcher fleet deliveries."""

from __future__ import annotations

import json

from yoke_core.domain.steering_fleet_report_compose import CombinedFleetReport
from yoke_core.domain.steering_fleet_report_project_rows import rows_per_section
from yoke_core.domain.steering_fleet_report_render import (
    REPORT_BEGIN,
    REPORT_END,
    scope_actionable_digest,
)


def combined_hook_digest(
    combined: CombinedFleetReport, prior_fingerprint: str = ""
) -> str:
    """Render changed scopes only; an identical report delivers nothing."""
    current = json.loads(combined.fingerprint())
    try:
        prior = json.loads(prior_fingerprint) if prior_fingerprint else {}
    except ValueError:
        prior = {}
    if not isinstance(prior, dict):
        prior = {}
    changed = {key for key, value in current.items() if prior.get(key) != value}
    parts = [REPORT_BEGIN]
    if "unattended" in changed and (combined.unattended or "unattended" in prior):
        parts.extend([
            "## unattended linked work",
            *(f"  {row.finding}" for row in combined.unattended),
            *([] if combined.unattended else ["  none"]),
            "",
        ])
    shared = rows_per_section([section.report for section in combined.sections])
    for section, rows in zip(combined.sections, shared):
        if f"scope:{section.descriptor}" not in changed:
            continue
        body = scope_actionable_digest(section.report, rows)
        if body or f"scope:{section.descriptor}" in prior:
            parts.extend([f"## {section.descriptor}", body or "  none", ""])
    for key in sorted(prior.keys() - current.keys()):
        if key.startswith("scope:"):
            parts.extend([f"## {key.removeprefix('scope:')}", "  no longer held", ""])
    parts.extend([
        f"{len(current) - len(changed)} section(s) unchanged; "
        "yoke steering report get --full",
        REPORT_END,
    ])
    return "\n".join(parts)


__all__ = ["combined_hook_digest"]
