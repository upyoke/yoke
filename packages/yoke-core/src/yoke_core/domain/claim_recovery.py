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
