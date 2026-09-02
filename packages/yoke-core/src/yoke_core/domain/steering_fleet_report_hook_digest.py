"""Compact fleet-report body for hook context.

The full combined body stays on ``yoke steering report get``. Hook injection
gets the actionable sections, this session's unacked inbox, and a pull
command so a harness inline cap cannot hide the delivery behind a live-claims
dump.
"""

from __future__ import annotations

from yoke_core.domain.steering_fleet_report_compose import CombinedFleetReport
from yoke_core.domain.steering_fleet_report_inbox import unacked_section_lines
from yoke_core.domain.steering_fleet_report_render import (
    REPORT_BEGIN,
    REPORT_END,
    scope_actionable_digest,
)


DIGEST_PREAMBLE = (
    "Hook digest of control-plane state. Pull the rest with "
    "`yoke steering report get` (covers every steering claim this session "
    "holds; pass `--project P` only to filter to one scope)."
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
    for section in combined.sections:
        digest = scope_actionable_digest(section.report)
        if not digest:
            continue
        parts.extend([f"## {section.descriptor}", digest, ""])
    if parts[-1] != "":
        parts.append("")
    parts.append(REPORT_END)
    return "\n".join(parts)


__all__ = ["DIGEST_PREAMBLE", "combined_hook_digest"]
