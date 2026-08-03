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
    route = core._skill_skip_route(
        workflow,
        current_status,
        skill_id="refine",
    )

    hops_written = core._walk_hops(
        item_id,
        hops=route.hops,
        bypass_reason=core.BYPASS_SKIP_REFINE,
        allowlist=route.allowed_hops,
        out=out,
    )

    finalize._emit_skip_event(
        item_id,
        via=core.BYPASS_SKIP_REFINE,
        from_status=current_status,
        to_status=route.to_stage,
        skipped_phase=route.skipped_phase,
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
        "to_status": route.to_stage,
        "skipped_phase": route.skipped_phase,
        "hops_written": hops_written,
        "claim_release": release_result,
    }


__all__ = ["skip_refine"]
