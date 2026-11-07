"""Canonical identity helpers for claim-recovery instructions."""

from __future__ import annotations

from typing import Optional


def canonical_item_ref(item_id: int) -> Optional[str]:
    """Return the public ref used by an item-claim recovery command."""
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.project_identity import render_item_ref

        with db_helpers.connect() as conn:
            return render_item_ref(conn, item_id)
    except Exception:
        return None


def terminal_progress_log_recovery(item_id: int, public_ref: str) -> Optional[str]:
    """Teach the checkpoint rule when the item has already finished."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.item_terminal_resources import item_is_terminal

    with db_helpers.connect() as conn:
        if not item_is_terminal(conn, item_id):
            return None
    return (
        f"item {public_ref} is terminal; its result is already recorded — "
        "skip the final checkpoint (.yoke/docs/agents/rules.md → Items and the Progress Log)"
    )
