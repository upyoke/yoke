"""Compact fleet-report body for hook context.

The full combined body stays on ``yoke steering report get --full``. Hook injection
gets the actionable sections, this session's unacked inbox, and a pull
command so a harness inline cap cannot hide the delivery behind a live-claims
dump.
"""

from __future__ import annotations

from yoke_core.domain.steering_fleet_report_compose import CombinedFleetReport
from yoke_core.domain.steering_fleet_report_inbox import unacked_section_lines
from yoke_core.domain.steering_fleet_report_project_rows import rows_per_section
from yoke_core.domain.steering_fleet_report_render import (
    REPORT_BEGIN,
    REPORT_END,
    scope_actionable_digest,
)


#: One line, because it rides every digest. What the digest withholds and
#: what each section means are answered by the commands it names.
DIGEST_PREAMBLE = (
    "Hook digest — machines, surfaces, balances and live claims: "
    "`yoke steering report get --full`; sections explained: "
    "`yoke steering report get --help`."
)


def combined_hook_digest(combined: CombinedFleetReport) -> str:
    """Actionable sections plus this session's unacked injected inbox."""
    parts = [
        REPORT_BEGIN,
        (
            f"composed {combined.composed_at} · {len(combined.sections)} "
            "held scopes · hook digest"
        ),
        DIGEST_PREAMBLE,
        "",
        *unacked_section_lines(combined.unacked_injected),
    ]
    if combined.unacked_injected:
        parts.append("")
    if combined.unattended:
        parts.extend(
            [
                "## unattended linked work",
                *(f"  {row.finding}" for row in combined.unattended),
                "",
            ]
        )
    shared = rows_per_section([section.report for section in combined.sections])
    for section, rows in zip(combined.sections, shared):
        digest = scope_actionable_digest(section.report, rows)
        if not digest:
            continue
        parts.extend([f"## {section.descriptor}", digest, ""])
    if parts[-1] != "":
        parts.append("")
    parts.append(REPORT_END)
    return "\n".join(parts)


__all__ = ["DIGEST_PREAMBLE", "combined_hook_digest"]
