"""Skip-refine flow for operator-asserted advance skips."""

from __future__ import annotations

import sys
from typing import Optional, TextIO

from yoke_core.domain import advance_skip_core as core
from yoke_core.domain import advance_skip_finalize as finalize
from yoke_core.domain.lifecycle import EPIC_PROGRESSION, ISSUE_PROGRESSION


def skip_refine(
    item_id: int,
    *,
    session_id: Optional[str] = None,
    out: TextIO = sys.stdout,
) -> dict:
    """Advance past an idea or plan refining phase in one sanctioned call."""
    current_status, item_type = core._lookup_item(item_id)
    if current_status not in core._REFINE_ROUTING:
        raise ValueError(
            f"--skip-refine requires current status in "
            f"{sorted(core._REFINE_ROUTING)!r}, got {current_status!r}. "
            "This flag replaces a refining phase - it has no meaning at "
            "other statuses."
        )

    if current_status in {"plan-drafted", "refining-plan"} and item_type == "issue":
        raise ValueError(
            "--skip-refine on plan-refinement statuses requires an epic item; "
            "the issue progression has no plan-refining phase."
        )

    hops, skipped_phase = core._REFINE_ROUTING[current_status]
    target = hops[-1]

    progression = ISSUE_PROGRESSION if item_type == "issue" else EPIC_PROGRESSION
    if target not in progression:
        raise ValueError(
            f"Target status {target!r} is not in the {item_type} progression - "
            "refusing to advance."
        )

    hops_written = core._walk_hops(
        item_id,
        hops=hops,
        bypass_reason=core.BYPASS_SKIP_REFINE,
        allowlist=core._REFINE_TARGETS_ALLOWED,
        out=out,
    )

    finalize._emit_skip_event(
        item_id,
        via=core.BYPASS_SKIP_REFINE,
        from_status=current_status,
        to_status=target,
        skipped_phase=skipped_phase,
        out=out,
    )

    release_result = finalize._release_claim(
        item_id,
        reason="finalize-exit",
        session_id=session_id,
        out=out,
    )

    return {
        "success": True,
        "via": core.BYPASS_SKIP_REFINE,
        "from_status": current_status,
        "to_status": target,
        "skipped_phase": skipped_phase,
        "hops_written": hops_written,
        "claim_release": release_result,
    }


__all__ = ["skip_refine"]
