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


#: The decisions the digest does not serve, named as decisions rather than
#: as section headings. A reader weighs whether to pull by what they are
#: about to decide, not by what a heading is called, and the launch
#: allocation these sections carry is decided while composing a launch —
#: nowhere near the report.
WITHHELD_DECISIONS: tuple[str, ...] = (
    "which machine and surface to launch on",
    "how much plan headroom each surface has left",
    "how many sessions each surface is already running",
    "whether a relay is healthy enough to launch on",
    "which model each surface is serving",
)

DIGEST_PREAMBLE = (
    "Hook digest of control-plane state: quiet detectors, available work, and "
    "this session's unacked inbox. It does not answer "
    + "; ".join(WITHHELD_DECISIONS)
    + " — `yoke steering report get` answers those (covers every steering "
    "claim this session holds; pass `--project P` only to filter to one "
    "scope)."
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
