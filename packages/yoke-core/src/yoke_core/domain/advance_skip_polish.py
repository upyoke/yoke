"""Skip-polish flow for operator-asserted advance skips."""

from __future__ import annotations

import sys
from typing import Optional, TextIO

from yoke_core.domain import advance_skip_core as core
from yoke_core.domain import advance_skip_finalize as finalize


def skip_polish(
    item_id: int,
    *,
    session_id: Optional[str] = None,
    out: TextIO = sys.stdout,
) -> dict:
    """Advance an item from ``reviewed-implementation`` to ``implemented``."""
    current_status, _item_type = core._lookup_item(item_id)
    if current_status != core._POLISH_START:
        raise ValueError(
            f"--skip-polish requires current status {core._POLISH_START!r}, "
            f"got {current_status!r}. Reach {core._POLISH_START!r} via the "
            "normal review loop before invoking --skip-polish."
        )

    hops_written = core._walk_hops(
        item_id,
        hops=[core._POLISH_TRANSIT, core._POLISH_END],
        bypass_reason=core.BYPASS_SKIP_POLISH,
        allowlist=core._POLISH_TRANSIT_ALLOWED,
        out=out,
    )

    finalize._emit_skip_event(
        item_id,
        via=core.BYPASS_SKIP_POLISH,
        from_status=core._POLISH_START,
        to_status=core._POLISH_END,
        skipped_phase=core._POLISH_TRANSIT,
        out=out,
    )

    release_result = finalize._release_claim(
        item_id,
        reason="handoff-to-usher",
        session_id=session_id,
        out=out,
    )

    return {
        "success": True,
        "via": core.BYPASS_SKIP_POLISH,
        "from_status": core._POLISH_START,
        "to_status": core._POLISH_END,
        "skipped_phase": core._POLISH_TRANSIT,
        "hops_written": hops_written,
        "claim_release": release_result,
    }


__all__ = ["skip_polish"]
