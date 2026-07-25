"""Skip-refine flow for operator-asserted advance skips."""

from __future__ import annotations

import sys
from typing import Optional, TextIO

from yoke_core.domain import advance_skip_core as core
from yoke_core.domain import advance_skip_finalize as finalize


def skip_refine(
    item_id: int,
    *,
    session_id: Optional[str] = None,
    out: TextIO = sys.stdout,
) -> dict:
    """Advance past an idea or plan refining phase in one sanctioned call."""
    current_status, workflow = core._lookup_item(item_id)
    if current_status not in core._REFINE_ROUTING:
        raise ValueError(
            f"--skip-refine requires current status in "
            f"{sorted(core._REFINE_ROUTING)!r}, got {current_status!r}. "
            "This flag replaces a refining phase - it has no meaning at "
            "other statuses."
        )

    hops, skipped_phase = core._REFINE_ROUTING[current_status]
    target = hops[-1]

    if not workflow.accepts_stage(target):
        raise ValueError(
            f"Target stage {target!r} is not declared by "
            f"{workflow.workflow_id}@{workflow.version}; refusing to advance."
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
